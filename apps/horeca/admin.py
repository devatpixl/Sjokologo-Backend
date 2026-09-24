"""Django admin for the HORECA portal.

The Next.js admin panel has no HORECA screens yet, so without this the only way
to approve a company, review a logo or change the capacity cap is curl. These
registrations are deliberately plain — they exist so the portal is operable and
testable today, not as a replacement for the panel screens.

Approving and rejecting go through the same service functions the API uses, so
a decision made here fires the same customer e-mail and writes the same
history. A bare `save()` would change the row and tell nobody.
"""
from django import forms
from django.contrib import admin, messages
from django.db import transaction
from django.utils import timezone

from apps.users.models import CustomUser
from apps.users.password_setup import build_password_link

from apps.emails import (
    send_horeca_company_approved_email,
    send_horeca_invite_email,
    send_horeca_company_rejected_email,
    send_horeca_logo_approved_email,
    send_horeca_logo_rejected_email,
)

from .models import (
    BlackoutDate,
    CapacityOverride,
    Company,
    DeliveryAddress,
    HorecaOrder,
    HorecaOrderEvent,
    HorecaOrderLine,
    HorecaProduct,
    HorecaSettings,
    Logo,
    Membership,
)


class CompanyAdminForm(forms.ModelForm):
    """Adds the contact person to the *create* form only.

    Creating a company by hand otherwise means four separate steps — add user,
    add company, add membership, and then no way at all to give the person a
    password. This collapses that into one screen and reuses the invite mail
    K-8 already sends, so the customer sets their own password and we never
    handle one.
    """

    contact_email = forms.EmailField(
        required=False,
        label='Kontaktperson — e-post',
        help_text='Opprettes som bedriftsadmin og får en e-post med lenke for å '
                  'velge passord. La stå tom for å legge til brukere senere.',
    )
    contact_person_name = forms.CharField(
        required=False, label='Kontaktperson — navn', max_length=255,
    )

    class Meta:
        model = Company
        fields = '__all__'

    def clean_contact_email(self):
        email = (self.cleaned_data.get('contact_email') or '').strip().lower()
        if not email:
            return ''
        existing = CustomUser.objects.filter(email__iexact=email).first()
        # A consumer account is a real person with a real password and an order
        # history; quietly converting it into a company login would be a
        # surprise for them and a support call for us.
        if existing and existing.user_type == 'registered':
            raise forms.ValidationError(
                f'{email} har allerede en vanlig kundekonto. Bruk en annen '
                'adresse, eller legg brukeren til manuelt under Medlemskap.'
            )
        return email


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fields = ('user', 'role', 'is_active', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    form = CompanyAdminForm
    list_display = ('name', 'org_number', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'org_number', 'email')
    readonly_fields = ('approved_at', 'approved_by', 'created_at', 'updated_at')
    inlines = [MembershipInline]
    actions = ('approve', 'reject')

    def get_fieldsets(self, request, obj=None):
        """The contact fields only make sense while creating."""
        fs = super().get_fieldsets(request, obj)
        if obj is not None:
            fs = [(name, {**opts, 'fields': [
                f for f in opts['fields']
                if f not in ('contact_email', 'contact_person_name')
            ]}) for name, opts in fs]
        return fs

    def save_model(self, request, obj, form, change):
        """Create the company, its first user and the invitation in one go.

        A company WE create is already vetted — we typed it in — so it goes
        straight to ACTIVE rather than sitting in the pending queue waiting for
        us to approve our own work.
        """
        creating = not change
        if creating and not obj.status:
            obj.status = Company.Status.ACTIVE
        if creating and obj.status == Company.Status.ACTIVE and not obj.approved_at:
            obj.approved_at = timezone.now()
            obj.approved_by = request.user

        email = (form.cleaned_data.get('contact_email') or '').strip().lower()
        if not (creating and email):
            super().save_model(request, obj, form, change)
            return

        # One transaction: a company with no way in is worse than no company.
        with transaction.atomic():
            super().save_model(request, obj, form, change)
            user = CustomUser.objects.filter(email__iexact=email).first()
            needs_password = user is None or not user.has_usable_password()
            if user is None:
                user = CustomUser.objects.create(
                    email=email,
                    name=form.cleaned_data.get('contact_person_name', '').strip(),
                    user_type='horeca',
                )
                user.set_unusable_password()
                user.save(update_fields=['password'])
            elif user.user_type == 'guest':
                # A guest-checkout shell is not a real account; promoting it is
                # safe and keeps their e-mail as the single identity.
                user.user_type = 'horeca'
                user.save(update_fields=['user_type'])

            Membership.objects.get_or_create(
                user=user, company=obj,
                defaults={
                    'role': Membership.Role.BEDRIFTSADMIN,
                    'invited_by': request.user,
                    'invited_at': timezone.now(),
                },
            )

        # Outside the transaction: a dead SMTP must not roll back the company.
        try:
            send_horeca_invite_email(
                user, obj,
                inviter_name=request.user.name or '',
                password_url=build_password_link(user) if needs_password else None,
            )
            self.message_user(
                request,
                f'{obj.name} opprettet. {email} er lagt til som bedriftsadmin '
                'og har fått e-post med lenke for å velge passord.',
            )
        except Exception:
            self.message_user(
                request,
                f'{obj.name} opprettet med {email} som bedriftsadmin, men '
                'e-posten feilet. Send dem lenken manuelt.',
                level=messages.WARNING,
            )

    def _contact(self, company):
        member = (company.members.filter(is_active=True)
                  .select_related('user')
                  .order_by('-role').first())
        return member.user if member else None

    @admin.action(description='Godkjenn — kunden får e-post og kan bestille')
    def approve(self, request, queryset):
        done = 0
        for company in queryset.exclude(status=Company.Status.ACTIVE):
            company.status = Company.Status.ACTIVE
            company.rejection_reason = ''
            company.approved_at = timezone.now()
            company.approved_by = request.user
            company.save()
            contact = self._contact(company)
            if contact:
                try:
                    send_horeca_company_approved_email(contact, company)
                except Exception:
                    self.message_user(
                        request, f'{company.name}: godkjent, men e-posten feilet.',
                        level=messages.WARNING,
                    )
            done += 1
        self.message_user(request, f'{done} bedrift(er) godkjent.')

    @admin.action(description='Avvis (uten begrunnelse — bruk API-et for det)')
    def reject(self, request, queryset):
        for company in queryset.exclude(status=Company.Status.REJECTED):
            company.status = Company.Status.REJECTED
            company.save()
            contact = self._contact(company)
            if contact:
                try:
                    send_horeca_company_rejected_email(
                        contact, company, company.rejection_reason,
                    )
                except Exception:
                    pass
        # K-29's spirit: a rejection without a reason tells the customer
        # nothing. The API requires one; this action cannot, so say so.
        self.message_user(
            request,
            'Avvist. Skriv gjerne inn en begrunnelse på bedriften og send '
            'beskjed manuelt — kunden fikk ingen forklaring.',
            level=messages.WARNING,
        )


@admin.register(Logo)
class LogoAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'status', 'detected_format',
                    'width_px', 'height_px', 'created_at')
    list_filter = ('status', 'kind')
    search_fields = ('name', 'company__name')
    readonly_fields = ('company', 'file', 'original_filename', 'detected_format',
                       'kind', 'byte_size', 'checksum_sha256', 'width_px',
                       'height_px', 'uploaded_by', 'created_at')
    actions = ('approve',)

    @admin.action(description='Godkjenn logo — kunden får e-post')
    def approve(self, request, queryset):
        for logo in queryset.exclude(status=Logo.Status.APPROVED):
            logo.status = Logo.Status.APPROVED
            logo.rejection_reason = ''
            logo.reviewed_at = timezone.now()
            logo.reviewed_by = request.user
            logo.save()
            if logo.uploaded_by:
                try:
                    send_horeca_logo_approved_email(logo.uploaded_by, logo)
                except Exception:
                    pass
        self.message_user(request, 'Logo(er) godkjent.')

    def save_model(self, request, obj, form, change):
        """Rejecting from the detail page still mails the reason."""
        previous = Logo.objects.filter(pk=obj.pk).values_list('status', flat=True).first()
        super().save_model(request, obj, form, change)
        if previous != obj.status and obj.status == Logo.Status.REJECTED:
            obj.reviewed_at = timezone.now()
            obj.reviewed_by = request.user
            obj.save(update_fields=['reviewed_at', 'reviewed_by'])
            if obj.uploaded_by:
                try:
                    send_horeca_logo_rejected_email(
                        obj.uploaded_by, obj, obj.rejection_reason,
                    )
                except Exception:
                    pass


class OrderLineInline(admin.TabularInline):
    model = HorecaOrderLine
    extra = 0
    # Every one of these is a snapshot taken when the order was sent. Editing
    # them here would rewrite history without touching the totals.
    readonly_fields = ('product', 'product_name', 'tray_count', 'with_logo',
                       'logo_name', 'pieces_per_tray', 'piece_count',
                       'unit_price_ex_vat', 'line_total_ex_vat')
    can_delete = False


class EventInline(admin.TabularInline):
    model = HorecaOrderEvent
    extra = 0
    readonly_fields = ('from_status', 'to_status', 'actor_name', 'source',
                       'note', 'created_at')
    can_delete = False


@admin.register(HorecaOrder)
class HorecaOrderAdmin(admin.ModelAdmin):
    list_display = ('order_number', 'company_name', 'status', 'delivery_date',
                    'delivery_window_label', 'tray_count', 'total_inc_vat')
    list_filter = ('status', 'is_draft', 'delivery_date')
    search_fields = ('order_number', 'company_name', 'org_number')
    date_hierarchy = 'delivery_date'
    inlines = [OrderLineInline, EventInline]
    readonly_fields = ('order_number', 'company', 'placed_by', 'tray_count',
                       'subtotal_ex_vat', 'vat_amount', 'total_inc_vat',
                       'created_at', 'updated_at')


@admin.register(HorecaProduct)
class HorecaProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'wholesale_price', 'pieces_per_tray_plain',
                    'pieces_per_tray_logo', 'lead_time_days', 'is_active')
    list_editable = ('wholesale_price', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(HorecaSettings)
class HorecaSettingsAdmin(admin.ModelAdmin):
    """K-41 — lead times and capacity are settings, not constants."""

    def has_add_permission(self, request):
        return False  # singleton; the row is created by a data migration

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    list_display = ('label', 'company', 'street', 'postal_code', 'city',
                    'is_default', 'is_archived')
    list_filter = ('is_archived',)
    search_fields = ('label', 'street', 'city', 'company__name')


admin.site.register(BlackoutDate)
admin.site.register(CapacityOverride)
