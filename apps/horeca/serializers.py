"""Serializers for the HORECA portal."""
from django.db import transaction
from rest_framework import serializers

from apps.users.models import CustomUser

from .models import (
    Company,
    DeliveryAddress,
    HorecaOrder,
    HorecaOrderEvent,
    HorecaOrderLine,
    HorecaProduct,
    Logo,
    Membership,
)

# Weights for the Norwegian organisasjonsnummer MOD-11 check digit.
_ORGNR_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)


def validate_org_number(value: str) -> str:
    """Normalise and check a Norwegian org number.

    Worth doing properly rather than just counting digits: `org_number` is
    unique, so a transposed pair does not bounce — it silently creates a second
    company that looks legitimate and has to be merged by hand later.
    """
    digits = ''.join(ch for ch in value if ch.isdigit())
    if len(digits) != 9:
        raise serializers.ValidationError(
            'Organisasjonsnummer må være 9 siffer.'
        )
    total = sum(int(d) * w for d, w in zip(digits[:8], _ORGNR_WEIGHTS))
    remainder = total % 11
    check = 0 if remainder == 0 else 11 - remainder
    if check == 10 or check != int(digits[8]):
        raise serializers.ValidationError(
            'Organisasjonsnummeret ser ikke riktig ut. Sjekk tallene.'
        )
    return digits


class CompanyRegisterSerializer(serializers.Serializer):
    """K-5 — a business signs itself up and waits for approval."""

    company_name = serializers.CharField(max_length=255)
    org_number = serializers.CharField(max_length=32)
    contact_name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=32)

    invoice_street = serializers.CharField(max_length=255)
    invoice_postal_code = serializers.CharField(max_length=16)
    invoice_city = serializers.CharField(max_length=128)

    def validate_org_number(self, value):
        digits = validate_org_number(value)
        if Company.objects.filter(org_number=digits).exists():
            # Deliberately not "that company exists" with no way forward. The
            # second person at a company is meant to arrive by invitation from
            # their own bedriftsadmin (K-8), so say that.
            raise serializers.ValidationError(
                'Denne bedriften er allerede registrert. Be en kollega med '
                'bedriftsadmin-tilgang om å invitere deg.'
            )
        return digits

    @transaction.atomic
    def create(self, validated):
        email = validated['email'].strip().lower()

        company = Company.objects.create(
            name=validated['company_name'].strip(),
            org_number=validated['org_number'],
            email=email,
            phone=validated['phone'].strip(),
            invoice_street=validated['invoice_street'].strip(),
            invoice_postal_code=validated['invoice_postal_code'].strip(),
            invoice_city=validated['invoice_city'].strip(),
            status=Company.Status.PENDING,
        )

        # An e-mail already in use is not an error. CustomUser.email is unique
        # and is the login field, so a second account is impossible anyway —
        # and a chef who already shops here privately should keep one login.
        # Their existing user_type is left alone on purpose: they really are
        # still a consumer customer, and rewriting it would quietly remove them
        # from the shop's own figures.
        user = CustomUser.objects.filter(email__iexact=email).first()
        created_user = user is None

        # A guest-checkout row is NOT a usable account: apps/users/views.py
        # creates those with user_type='guest' and set_unusable_password().
        # Treating one as "already has a login" hands them a company they can
        # never sign in to. Anyone without a usable password needs the link.
        needs_password = created_user or not user.has_usable_password()

        if not created_user and user.user_type == 'guest':
            # Promote the shell. A guest is not a consumer customer anyone is
            # counting, so unlike a 'registered' user this one is safe to move.
            user.user_type = 'horeca'
            if not user.name:
                user.name = validated['contact_name'].strip()
            user.save(update_fields=['user_type', 'name'])

        if created_user:
            user = CustomUser.objects.create(
                email=email,
                name=validated['contact_name'].strip(),
                user_type='horeca',
                phone=validated['phone'].strip(),
            )
            # No password yet. They set one from the link in their e-mail, the
            # same way consumer signup works (apps/users/views.py:register_view).
            user.set_unusable_password()
            user.save(update_fields=['password'])

        Membership.objects.create(
            user=user,
            company=company,
            # Whoever registers the company is its first administrator —
            # otherwise nobody could ever invite anyone (K-8).
            role=Membership.Role.BEDRIFTSADMIN,
        )

        self.context['needs_password'] = needs_password
        self.context['user'] = user
        return company


class CompanySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Company
        fields = [
            'id', 'name', 'org_number', 'status', 'status_label',
            'rejection_reason', 'phone', 'email',
            'invoice_street', 'invoice_postal_code', 'invoice_city',
            'created_at',
        ]
        read_only_fields = fields


class MembershipSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='user.name', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    role_label = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = Membership
        fields = ['id', 'name', 'email', 'role', 'role_label', 'is_active', 'created_at']
        read_only_fields = fields


# ── Catalogue (K-11 … K-15) ─────────────────────────────────────────────────

class HorecaProductSerializer(serializers.ModelSerializer):
    """The varebok. Prices are masked until the company is approved.

    K-6 and K-11 read together: an unapproved company may browse, but wholesale
    prices are not public. `pricing.may_see_prices` gates this a second time at
    the resolver, because getting this wrong is embarrassing in a way that is
    hard to walk back.
    """
    price_ex_vat = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    pieces = serializers.SerializerMethodField()

    class Meta:
        model = HorecaProduct
        fields = [
            'id', 'slug', 'name', 'short_description', 'description',
            'pieces_per_tray_plain', 'pieces_per_tray_logo', 'logo_available',
            'pieces', 'price_ex_vat', 'vat_rate',
            'ingredients_text', 'allergens', 'traces_of',
            'net_weight_grams', 'shelf_life_days', 'storage_text',
            'image_url', 'lead_time_days', 'is_active',
        ]

    def get_pieces(self, obj):
        """Both counts in one place, so the UI never recomputes 88 vs 81."""
        return {'plain': obj.pieces_per_tray_plain, 'logo': obj.pieces_per_tray_logo}

    def get_price_ex_vat(self, obj):
        if not self.context.get('show_prices'):
            return None
        return str(obj.wholesale_price)

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get('request')
        url = obj.image.url
        return request.build_absolute_uri(url) if request else url


class HorecaProductAdminSerializer(serializers.ModelSerializer):
    """Admin CRUD — prices always visible, everything writable."""

    class Meta:
        model = HorecaProduct
        fields = '__all__'

    def validate_wholesale_price(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Prisen må være større enn 0.')
        return value

    def validate(self, attrs):
        plain = attrs.get('pieces_per_tray_plain',
                          getattr(self.instance, 'pieces_per_tray_plain', None))
        logo = attrs.get('pieces_per_tray_logo',
                         getattr(self.instance, 'pieces_per_tray_logo', None))
        if plain and logo and logo > plain:
            # K-12 — the logo sheet replaces chocolates, so a logo tray can
            # never hold more than a plain one.
            raise serializers.ValidationError({
                'pieces_per_tray_logo':
                    'Et brett med logo kan ikke ha flere biter enn uten.',
            })
        return attrs


# ── Delivery addresses (K-33 … K-38) ────────────────────────────────────────

class DeliveryAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAddress
        fields = [
            'id', 'label', 'recipient', 'contact_name', 'contact_phone',
            'street', 'postal_code', 'city', 'country',
            'instructions', 'is_default', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def validate_contact_phone(self, value):
        # K-36 makes this required on purpose: the driver needs somebody to ring.
        digits = ''.join(ch for ch in (value or '') if ch.isdigit())
        if len(digits) < 8:
            raise serializers.ValidationError(
                'Oppgi et telefonnummer sjåføren kan ringe.'
            )
        return value

    def validate_postal_code(self, value):
        digits = ''.join(ch for ch in (value or '') if ch.isdigit())
        if len(digits) != 4:
            raise serializers.ValidationError('Postnummer må være 4 siffer.')
        return digits


# ── Logos (K-24 … K-32) ─────────────────────────────────────────────────────

class LogoSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Logo
        fields = [
            'id', 'name', 'original_filename', 'detected_format', 'kind',
            'byte_size', 'width_px', 'height_px',
            'status', 'status_label', 'rejection_reason', 'is_usable',
            'is_archived', 'created_at', 'reviewed_at',
        ]
        read_only_fields = fields


# ── Orders (K-16 … K-23) ────────────────────────────────────────────────────

class HorecaOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = HorecaOrderLine
        fields = [
            'id', 'product', 'product_name', 'product_slug',
            'tray_count', 'with_logo', 'logo', 'logo_name',
            'pieces_per_tray', 'piece_count',
            'unit_price_ex_vat', 'vat_rate', 'line_total_ex_vat',
            'allergens_snapshot', 'ingredients_snapshot', 'line_note',
        ]
        read_only_fields = fields


class HorecaOrderEventSerializer(serializers.ModelSerializer):
    to_label = serializers.SerializerMethodField()

    class Meta:
        model = HorecaOrderEvent
        fields = ['id', 'from_status', 'to_status', 'to_label',
                  'actor_name', 'source', 'note', 'created_at']
        read_only_fields = fields

    def get_to_label(self, obj):
        return dict(HorecaOrder.Status.choices).get(obj.to_status, obj.to_status)


class HorecaOrderSerializer(serializers.ModelSerializer):
    lines = HorecaOrderLineSerializer(many=True, read_only=True)
    events = HorecaOrderEventSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    can_cancel = serializers.SerializerMethodField()
    piece_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = HorecaOrder
        fields = [
            'id', 'order_number', 'status', 'status_label', 'is_draft',
            'delivery_date', 'delivery_window', 'delivery_window_label',
            'company_name', 'org_number',
            'delivery_label', 'delivery_recipient', 'delivery_contact_name',
            'delivery_contact_phone', 'delivery_street', 'delivery_postal_code',
            'delivery_city', 'delivery_country', 'delivery_instructions',
            'production_note',
            'subtotal_ex_vat', 'vat_amount', 'total_inc_vat',
            'tray_count', 'piece_count',
            'placed_by_name', 'placed_by_email',
            'cancelled_at', 'cancellation_reason',
            'sent_at', 'created_at', 'updated_at',
            'lines', 'events', 'can_cancel',
        ]
        read_only_fields = fields

    def get_can_cancel(self, obj):
        return obj.can_be_cancelled_by_customer()


class OrderLineInputSerializer(serializers.Serializer):
    """One line as the portal sends it. Prices are NEVER accepted from the
    client — they are resolved server-side in pricing.resolve_unit_price."""
    product = serializers.SlugField()
    tray_count = serializers.IntegerField(min_value=1)
    with_logo = serializers.BooleanField(default=False)
    logo = serializers.UUIDField(required=False, allow_null=True)
    line_note = serializers.CharField(required=False, allow_blank=True,
                                      max_length=300, default='')


class OneOffAddressSerializer(serializers.Serializer):
    """K-35 — an address typed for a single order and never saved.

    Caterers deliver somewhere new most weeks; forcing every one-night venue
    into the saved-address book would turn it into a junk drawer within a
    month.
    """
    recipient = serializers.CharField(required=False, allow_blank=True,
                                      max_length=150, default='')
    contact_name = serializers.CharField(required=False, allow_blank=True,
                                         max_length=150, default='')
    contact_phone = serializers.CharField(max_length=32)
    street = serializers.CharField(max_length=300)
    postal_code = serializers.CharField(max_length=10)
    city = serializers.CharField(max_length=120)
    instructions = serializers.CharField(required=False, allow_blank=True,
                                         default='')
    label = serializers.CharField(required=False, allow_blank=True,
                                  max_length=120, default='Engangsadresse')

    def validate_contact_phone(self, value):
        # K-36 applies here too — the driver still needs somebody to ring.
        digits = ''.join(ch for ch in (value or '') if ch.isdigit())
        if len(digits) < 8:
            raise serializers.ValidationError(
                'Oppgi et telefonnummer sjåføren kan ringe.'
            )
        return value

    def validate_postal_code(self, value):
        digits = ''.join(ch for ch in (value or '') if ch.isdigit())
        if len(digits) != 4:
            raise serializers.ValidationError('Postnummer må være 4 siffer.')
        return digits


class OrderWriteSerializer(serializers.Serializer):
    """Create or update a draft (K-20). Sending it is a separate call."""
    lines = OrderLineInputSerializer(many=True)
    delivery_date = serializers.DateField(required=False, allow_null=True)
    delivery_window = serializers.CharField(required=False, allow_blank=True,
                                            max_length=16, default='')
    # Either a saved address by id, or a one-off typed inline (K-33 / K-35).
    address = serializers.UUIDField(required=False, allow_null=True)
    one_off_address = OneOffAddressSerializer(required=False, allow_null=True)
    production_note = serializers.CharField(required=False, allow_blank=True,
                                            default='')

    def validate(self, attrs):
        if attrs.get('address') and attrs.get('one_off_address'):
            raise serializers.ValidationError({
                'address': 'Velg enten en lagret adresse eller skriv inn en ny '
                           '— ikke begge.',
            })
        return attrs

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError('Legg til minst ett brett.')
        return value


class MemberInviteSerializer(serializers.Serializer):
    """K-8 — a bedriftsadmin invites a colleague by e-mail."""
    email = serializers.EmailField()
    name = serializers.CharField(required=False, allow_blank=True,
                                 max_length=150, default='')
    role = serializers.ChoiceField(
        choices=Membership.Role.choices, default=Membership.Role.BESTILLER,
    )
