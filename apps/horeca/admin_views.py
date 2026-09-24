"""Admin API for the HORECA portal.

House style: plain `@api_view` functions, hand-registered in config/urls.py's
flat `admin_patterns` list. Every one is explicitly `IsAdminUser` — see the note
in views.py about the AllowAny default.
"""
import csv
import logging
import tempfile
import zipfile
from datetime import datetime
from io import StringIO
from pathlib import Path

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status as http
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.emails import (
    send_horeca_company_approved_email,
    send_horeca_company_rejected_email,
    send_horeca_logo_approved_email,
    send_horeca_logo_rejected_email,
    send_horeca_order_cancelled_email,
    send_horeca_order_changed_email,
)
from apps.users.permissions import IsAdminUser

from .availability import first_available_date
from .models import (
    BlackoutDate,
    CapacityOverride,
    Company,
    HorecaOrder,
    HorecaOrderEvent,
    HorecaOrderLine,
    HorecaProduct,
    HorecaSettings,
    Logo,
    Membership,
)
from .notifications import send_status_change_email
from .services import (
    assert_can_enter_production,
    cancel_order,
    lock_delivery_day,
    record_event,
    validate_orderable,
)
from .serializers import (
    CompanyAdminWriteSerializer,
    CompanySerializer,
    HorecaOrderSerializer,
    HorecaProductAdminSerializer,
    LogoSerializer,
    MembershipSerializer,
)

log = logging.getLogger(__name__)


def _primary_contact(company):
    """The person to write to about this company.

    Its first administrator — the one who registered it. Falls back to any
    active member so an approval mail is not silently dropped if the original
    registrant has since been deactivated (K-3).
    """
    members = company.members.filter(is_active=True).select_related('user')
    admin = members.filter(role=Membership.Role.BEDRIFTSADMIN).first()
    member = admin or members.first()
    return member.user if member else None


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_horeca_company_list(request):
    """K-59 — the approval queue, and the full customer list behind it.

    POST creates a company and, optionally, its first user: the same thing the
    Django admin form does, so the panel does not have to send anyone to
    another app. A company we typed in is already vetted, so it is created
    ACTIVE rather than queueing for our own approval.
    """
    if request.method == 'POST':
        return _admin_create_company(request)

    qs = Company.objects.annotate(
        member_count=Count('members', filter=Q(members__is_active=True)),
    )

    status_filter = request.query_params.get('status')
    if status_filter:
        qs = qs.filter(status=status_filter)

    search = (request.query_params.get('search') or '').strip()
    if search:
        qs = qs.filter(
            Q(name__icontains=search) | Q(org_number__icontains=search)
        )

    # Pending first — this list is a work queue before it is a directory.
    # Ordered in the database rather than in Python so it keeps working once
    # there are more companies than fit comfortably in memory.
    qs = qs.annotate(
        is_pending=Case(
            When(status=Company.Status.PENDING, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
    ).order_by('is_pending', '-created_at')

    data = []
    for company in qs:
        row = CompanySerializer(company).data
        row['member_count'] = company.member_count
        # company.email is the invoice address and is often blank — the person
        # to actually write to is the first administrator, whose address is
        # their login. Without this the panel shows a dash next to a company
        # that plainly has a user.
        contact = _primary_contact(company)
        row['contact_email'] = contact.email if contact else ''
        row['contact_name'] = (contact.name or '') if contact else ''
        data.append(row)
    return Response(data)



def _admin_create_company(request):
    """Company + first user + invitation, in one transaction.

    Mirrors apps/horeca/admin.py's CompanyAdminForm — same rules, same e-mail —
    because two ways of creating a company that behave differently is how you
    get a customer who cannot log in.
    """
    from django.db import transaction
    from django.utils import timezone as _tz
    from apps.users.models import CustomUser
    from apps.users.password_setup import build_password_link
    from apps.emails import send_horeca_invite_email

    data = request.data
    email = (data.get('contact_email') or '').strip().lower()

    existing = CustomUser.objects.filter(email__iexact=email).first() if email else None
    # A consumer account is a real person with a password and an order history;
    # silently turning it into a company login is a support call waiting.
    if existing and existing.user_type == 'registered':
        return Response(
            {'contact_email': [
                f'{email} har allerede en vanlig kundekonto. Bruk en annen '
                'adresse, eller legg brukeren til manuelt etterpå.']},
            status=http.HTTP_400_BAD_REQUEST,
        )

    serializer = CompanyAdminWriteSerializer(data=data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        company = serializer.save(
            status=Company.Status.ACTIVE,
            approved_at=_tz.now(),
            approved_by=request.user,
            # The form asks for one address. Use it for the company record too
            # when nothing else was given, so invoices and mail have somewhere
            # to go rather than an empty field.
            **({'email': email} if email and not serializer.validated_data.get('email') else {}),
        )
        user = existing
        needs_password = user is None or not user.has_usable_password()
        if user is None and email:
            user = CustomUser.objects.create(
                email=email,
                name=(data.get('contact_person_name') or '').strip(),
                user_type='horeca',
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
        elif user is not None and user.user_type == 'guest':
            user.user_type = 'horeca'
            user.save(update_fields=['user_type'])

        if user is not None:
            Membership.objects.get_or_create(
                user=user, company=company,
                defaults={'role': Membership.Role.BEDRIFTSADMIN,
                          'invited_by': request.user,
                          'invited_at': _tz.now()},
            )

    # Outside the transaction: a dead SMTP must not roll back the company.
    if user is not None:
        try:
            send_horeca_invite_email(
                user, company,
                inviter_name=getattr(request.user, 'name', '') or '',
                password_url=build_password_link(user) if needs_password else None,
            )
        except Exception:
            log.exception('horeca admin invite mail failed for %s', email)

    row = CompanySerializer(company).data
    row['member_count'] = company.members.filter(is_active=True).count()
    return Response(row, status=http.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def admin_horeca_company_detail(request, pk):
    company = get_object_or_404(Company, pk=pk)

    if request.method == 'GET':
        data = CompanySerializer(company).data
        data['members'] = MembershipSerializer(
            company.members.select_related('user').all(), many=True,
        ).data
        return Response(data)

    # PATCH — the only mutation admin needs here is the approval decision.
    new_status = request.data.get('status')
    valid = {c for c, _ in Company.Status.choices}
    if new_status not in valid:
        return Response(
            {'detail': f'Ukjent status. Gyldige: {", ".join(sorted(valid))}.'},
            status=http.HTTP_400_BAD_REQUEST,
        )

    previous = company.status
    company.status = new_status

    if new_status == Company.Status.ACTIVE:
        company.rejection_reason = ''
        company.approved_at = timezone.now()
        company.approved_by = request.user
    elif new_status in (Company.Status.REJECTED, Company.Status.SUSPENDED):
        company.rejection_reason = (request.data.get('rejection_reason') or '').strip()

    company.save()

    # Mail only on a real transition, so re-saving an already-approved company
    # does not tell the customer twice.
    if previous != new_status:
        contact = _primary_contact(company)
        if contact:
            try:
                if new_status == Company.Status.ACTIVE:
                    send_horeca_company_approved_email(contact, company)
                elif new_status == Company.Status.REJECTED:
                    send_horeca_company_rejected_email(
                        contact, company, company.rejection_reason,
                    )
            except Exception:
                log.exception('horeca status email crashed for %s', company.pk)

    return Response(CompanySerializer(company).data)


# ── Logo review (K-28, K-29) ────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_logo_list(request):
    """The review queue. Pending first — this is a work list before it is an
    archive."""
    qs = Logo.objects.select_related('company')
    if request.query_params.get('status'):
        qs = qs.filter(status=request.query_params['status'])
    qs = qs.annotate(
        is_pending=Case(
            When(status=Logo.Status.PENDING, then=Value(0)),
            default=Value(1), output_field=IntegerField(),
        ),
    ).order_by('is_pending', '-created_at')

    rows = []
    for logo in qs:
        row = LogoSerializer(logo).data
        row['company'] = logo.company.name
        row['company_id'] = str(logo.company_id)
        row['file_url'] = reverse('admin_horeca_logo_file', args=[logo.pk])
        rows.append(row)
    return Response(rows)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def admin_horeca_logo_detail(request, pk):
    logo = get_object_or_404(Logo.objects.select_related('company'), pk=pk)

    if request.method == 'GET':
        data = LogoSerializer(logo).data
        data['company'] = logo.company.name
        return Response(data)

    new_status = request.data.get('status')
    if new_status not in {Logo.Status.APPROVED, Logo.Status.REJECTED}:
        return Response({'detail': 'Status må være approved eller rejected.'},
                        status=http.HTTP_400_BAD_REQUEST)

    reason = (request.data.get('rejection_reason') or '').strip()
    if new_status == Logo.Status.REJECTED and not reason:
        # K-29 — a rejection with no reason tells the customer nothing and
        # guarantees they upload the same file again.
        return Response(
            {'rejection_reason': 'Skriv hvorfor logoen ikke kan brukes. '
                                 'Kunden får denne teksten.'},
            status=http.HTTP_400_BAD_REQUEST,
        )

    previous = logo.status
    logo.status = new_status
    logo.rejection_reason = reason if new_status == Logo.Status.REJECTED else ''
    logo.reviewed_at = timezone.now()
    logo.reviewed_by = request.user
    logo.save()

    if previous != new_status:
        contact = logo.uploaded_by or _primary_contact(logo.company)
        if contact:
            try:
                if new_status == Logo.Status.APPROVED:
                    send_horeca_logo_approved_email(contact, logo)
                else:
                    send_horeca_logo_rejected_email(contact, logo, reason)
            except Exception:
                log.exception('horeca logo email crashed for %s', logo.pk)

    return Response(LogoSerializer(logo).data)


@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_logo_file(request, pk):
    """Admin download. No company scoping here — that is the difference
    between this and the customer endpoint."""
    logo = get_object_or_404(Logo, pk=pk)
    response = FileResponse(
        logo.file.open('rb'),
        as_attachment=True,
        filename=logo.original_filename or f'{logo.name}.{logo.detected_format}',
        content_type='application/octet-stream',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    return response


# ── Orders (K-52, K-56) ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_order_list(request):
    qs = (HorecaOrder.objects
          .filter(is_draft=False)
          .select_related('company')
          .prefetch_related('lines'))

    params = request.query_params
    if params.get('status'):
        qs = qs.filter(status=params['status'])
    if params.get('company'):
        qs = qs.filter(company_id=params['company'])
    if params.get('search'):
        term = params['search'].strip()
        qs = qs.filter(
            Q(order_number__icontains=term)
            | Q(company_name__icontains=term)
            | Q(org_number__icontains=term)
        )
    if params.get('product'):
        # K-52 — "filtre på status, dato, kunde og produkt". distinct(), or an
        # order with two lines of the same tray appears twice.
        qs = qs.filter(lines__product__slug=params['product']).distinct()
    for key, lookup in (('delivery_from', 'gte'), ('delivery_to', 'lte')):
        raw = params.get(key)
        if raw:
            qs = qs.filter(**{f'delivery_date__{lookup}': raw})

    return Response(HorecaOrderSerializer(qs, many=True).data)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def admin_horeca_order_detail(request, order_number):
    order = get_object_or_404(
        HorecaOrder.objects.select_related('company').prefetch_related('lines', 'events'),
        order_number=order_number,
    )

    if request.method == 'GET':
        return Response(HorecaOrderSerializer(order).data)

    new_status = request.data.get('status')
    note = (request.data.get('note') or '').strip()

    if new_status and new_status != order.status:
        valid = {c for c, _ in HorecaOrder.Status.choices}
        if new_status not in valid:
            return Response({'detail': 'Ukjent status.'},
                            status=http.HTTP_400_BAD_REQUEST)

        if new_status == HorecaOrder.Status.AVBESTILT:
            cancel_order(order, actor=request.user, reason=note,
                         source=HorecaOrderEvent.Source.ADMIN)
            try:
                send_horeca_order_cancelled_email(order)
            except Exception:
                log.exception('horeca cancel email crashed for %s', order_number)
        else:
            # K-28 — nothing reaches the edible-sheet printer on artwork
            # nobody has looked at.
            if new_status == HorecaOrder.Status.PRODUKSJON:
                assert_can_enter_production(order)

            previous = order.status
            order.status = new_status
            if new_status == HorecaOrder.Status.BEKREFTET:
                order.confirmed_at = timezone.now()
            order.save(update_fields=['status', 'confirmed_at', 'updated_at'])
            record_event(order, from_status=previous, to_status=new_status,
                         actor=request.user,
                         source=HorecaOrderEvent.Source.ADMIN, note=note)
            # K-49 — one mail per real transition; internal states send none.
            send_status_change_email(order)

    elif note:
        # A note with no status change is still worth keeping in the history.
        record_event(order, from_status=order.status, to_status=order.status,
                     actor=request.user,
                     source=HorecaOrderEvent.Source.ADMIN, note=note)

    # K-56 — "Admin kan endre en ordre etter avtale med kunden, og endringen
    # står i ordrens historikk." Moving the slot re-checks capacity and lead
    # time exactly as a customer send would, so an agreed change cannot quietly
    # overbook a day.
    moved = {}
    for field in ('delivery_date', 'delivery_window'):
        if field in request.data and str(request.data[field] or '') != str(
            getattr(order, field) or ''
        ):
            moved[field] = request.data[field]

    if moved:
        with transaction.atomic():
            before = f'{order.delivery_date} {order.delivery_window_label}'.strip()
            if 'delivery_date' in moved:
                try:
                    order.delivery_date = datetime.strptime(
                        moved['delivery_date'], '%Y-%m-%d',
                    ).date()
                except (TypeError, ValueError):
                    return Response({'delivery_date': 'Ugyldig dato.'},
                                    status=http.HTTP_400_BAD_REQUEST)
            if 'delivery_window' in moved:
                cfg = HorecaSettings.load()
                code = moved['delivery_window']
                label = next((w['label'] for w in (cfg.delivery_windows or [])
                              if w['code'] == code), None)
                if label is None:
                    return Response({'delivery_window': 'Ukjent tidsvindu.'},
                                    status=http.HTTP_400_BAD_REQUEST)
                order.delivery_window = code
                order.delivery_window_label = label

            if order.delivery_date:
                lock_delivery_day(order.delivery_date)
            try:
                validate_orderable(order)
            except DRFValidationError as exc:
                return Response(exc.detail, status=http.HTTP_400_BAD_REQUEST)

            order.save()
            after = f'{order.delivery_date} {order.delivery_window_label}'.strip()
            record_event(
                order, from_status=order.status, to_status=order.status,
                actor=request.user, source=HorecaOrderEvent.Source.ADMIN,
                note=f'Levering flyttet fra {before} til {after}.'
                     + (f' {note}' if note else ''),
            )

        # The customer is told, because "vi flyttet leveringen" with no
        # explanation generates the phone call this portal exists to avoid.
        if str(request.data.get('notify', 'true')).lower() not in ('false', '0'):
            try:
                send_horeca_order_changed_email(order)
            except Exception:
                log.exception('horeca change email crashed for %s', order_number)

    if 'internal_note' in request.data:
        order.internal_note = request.data['internal_note']
        order.save(update_fields=['internal_note', 'updated_at'])

    order.refresh_from_db()
    return Response(HorecaOrderSerializer(order).data)


# ── The daily production list (K-53) ────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_production(request):
    """The SRS is explicit that this, not an order list, is what admin needs:
    "hva skal lages denne uka?"

    So it aggregates ACROSS orders by product and by logo, rather than listing
    orders and leaving the kitchen to add up trays by hand.
    """
    raw = request.query_params.get('date')
    try:
        day = datetime.strptime(raw, '%Y-%m-%d').date() if raw else timezone.localdate()
    except ValueError:
        return Response({'detail': 'Ugyldig dato.'}, status=http.HTTP_400_BAD_REQUEST)

    orders = (HorecaOrder.objects
              .filter(delivery_date=day, is_draft=False)
              .exclude(status=HorecaOrder.Status.AVBESTILT)
              .select_related('company')
              .prefetch_related('lines__logo', 'lines__product')
              .order_by('delivery_window', 'order_number'))

    by_product, by_logo = {}, {}
    for order in orders:
        for line in order.lines.all():
            entry = by_product.setdefault(line.product_slug, {
                'slug': line.product_slug,
                'name': line.product_name,
                'trays_plain': 0, 'trays_logo': 0,
                'pieces': 0, 'orders': set(),
            })
            if line.with_logo:
                entry['trays_logo'] += line.tray_count
            else:
                entry['trays_plain'] += line.tray_count
            entry['pieces'] += line.piece_count
            entry['orders'].add(order.order_number)

            if line.with_logo and line.logo_id:
                job = by_logo.setdefault(str(line.logo_id), {
                    'logo_id': str(line.logo_id),
                    'logo_name': line.logo_name,
                    'company': order.company_name,
                    'status': line.logo.status if line.logo else '',
                    'trays': 0,
                    'file_url': reverse('admin_horeca_logo_file', args=[line.logo_id]),
                })
                # Each tray needs its own edible sheet, so this is the number
                # the print shop actually works from.
                job['trays'] += line.tray_count

    cfg = HorecaSettings.load()
    override = CapacityOverride.objects.filter(date=day).first()
    capacity = override.max_trays if override else cfg.max_trays_per_day
    trays_booked = sum(o.tray_count for o in orders)

    return Response({
        'date': day,
        'capacity': capacity,
        'trays_booked': trays_booked,
        'trays_remaining': max(capacity - trays_booked, 0),
        'order_count': len(orders),
        'by_product': [
            {**row, 'orders': sorted(row['orders']),
             'trays': row['trays_plain'] + row['trays_logo']}
            for row in by_product.values()
        ],
        'logo_jobs': list(by_logo.values()),
        'orders': HorecaOrderSerializer(orders, many=True).data,
    })


# ── Settings, blackouts, capacity, catalogue ────────────────────────────────

_SETTINGS_FIELDS = [
    'max_trays_per_day', 'lead_time_days_plain', 'lead_time_days_logo',
    'lead_time_in_working_days', 'cutoff_time', 'order_horizon_days',
    'delivery_weekdays', 'delivery_windows',
    'pieces_per_tray_plain', 'pieces_per_tray_logo',
    'min_trays_per_order', 'max_trays_per_order',
    'cancel_deadline_days', 'vat_rate',
    'ordering_paused', 'paused_message', 'contact_phone',
]


@api_view(['GET', 'PATCH'])
@permission_classes([IsAdminUser])
def admin_horeca_settings(request):
    """K-41 is explicit that these are settings in the portal, not constants in
    the code. This is the endpoint that makes that true."""
    cfg = HorecaSettings.load()

    if request.method == 'PATCH':
        for field in _SETTINGS_FIELDS:
            if field in request.data:
                setattr(cfg, field, request.data[field])
        cfg.updated_by = request.user
        cfg.save()

    data = {field: getattr(cfg, field) for field in _SETTINGS_FIELDS}
    data['updated_at'] = cfg.updated_at
    # Close the loop for whoever just changed a number: show what it means.
    data['first_available_plain'] = first_available_date(has_logo=False, cfg=cfg)
    data['first_available_logo'] = first_available_date(has_logo=True, cfg=cfg)
    return Response(data)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_horeca_blackout_list(request):
    if request.method == 'POST':
        date_raw = request.data.get('date')
        if not date_raw:
            return Response({'date': 'Velg en dato.'},
                            status=http.HTTP_400_BAD_REQUEST)
        obj, _ = BlackoutDate.objects.update_or_create(
            date=date_raw,
            defaults={'reason': (request.data.get('reason') or '').strip()},
        )
        return Response({'id': obj.pk, 'date': obj.date, 'reason': obj.reason},
                        status=http.HTTP_201_CREATED)

    return Response([
        {'id': b.pk, 'date': b.date, 'reason': b.reason}
        for b in BlackoutDate.objects.filter(date__gte=timezone.localdate())
    ])


@api_view(['DELETE'])
@permission_classes([IsAdminUser])
def admin_horeca_blackout_detail(request, pk):
    get_object_or_404(BlackoutDate, pk=pk).delete()
    return Response(status=http.HTTP_204_NO_CONTENT)


@api_view(['GET', 'POST'])
@permission_classes([IsAdminUser])
def admin_horeca_product_list(request):
    if request.method == 'POST':
        serializer = HorecaProductAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=http.HTTP_201_CREATED)

    qs = HorecaProduct.objects.all()
    return Response(HorecaProductAdminSerializer(qs, many=True).data)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAdminUser])
def admin_horeca_product_detail(request, pk):
    product = get_object_or_404(HorecaProduct, pk=pk)

    if request.method == 'GET':
        return Response(HorecaProductAdminSerializer(product).data)

    if request.method == 'DELETE':
        # K-13 — deactivated, not deleted: order lines PROTECT the product, and
        # an order placed last month must keep rendering.
        product.is_active = False
        product.save(update_fields=['is_active', 'updated_at'])
        return Response(status=http.HTTP_204_NO_CONTENT)

    serializer = HorecaProductAdminSerializer(product, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


# ── Export (K-58) ───────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_order_export(request):
    """CSV with a UTF-8 BOM and ';' separators.

    Both details matter and are easy to lose: without the BOM Excel on Windows
    mangles æøå, and without ';' a Norwegian locale puts the whole row in one
    column. Copied from the one existing export in this project
    (apps/users/admin_views.py) rather than reinvented.
    """
    qs = (HorecaOrder.objects
          .filter(is_draft=False)
          .select_related('company')
          .order_by('-delivery_date'))
    for key, lookup in (('from', 'gte'), ('to', 'lte')):
        if request.query_params.get(key):
            qs = qs.filter(**{f'delivery_date__{lookup}': request.query_params[key]})
    if request.query_params.get('status'):
        qs = qs.filter(status=request.query_params['status'])

    buffer = StringIO()
    buffer.write('﻿')
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow([
        'Ordrenr', 'Status', 'Bedrift', 'Org.nr', 'Leveringsdato', 'Tidsvindu',
        'Brett', 'Sum eks mva', 'Mva', 'Totalt', 'Adresse', 'Bestilt av',
    ])
    for order in qs:
        writer.writerow([
            order.order_number, order.get_status_display(),
            order.company_name, order.org_number,
            order.delivery_date or '', order.delivery_window_label,
            order.tray_count,
            f'{order.subtotal_ex_vat:.2f}'.replace('.', ','),
            f'{order.vat_amount:.2f}'.replace('.', ','),
            f'{order.total_inc_vat:.2f}'.replace('.', ','),
            f'{order.delivery_street}, {order.delivery_postal_code} {order.delivery_city}',
            order.placed_by_name,
        ])

    stamp = timezone.localdate().strftime('%Y%m%d')
    response = HttpResponse(buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="horeca-ordrer-{stamp}.csv"'
    return response


# ── Packing list (K-54) ─────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_packing_list(request):
    """What the driver needs, per order: where, who to ring, when, and how to
    get in.

    Returned as JSON rather than a PDF: there is no PDF library in this
    project's requirements, and apps/products/label_views.py already
    establishes that layout lives client-side.
    """
    raw = request.query_params.get('date')
    order_number = request.query_params.get('order')

    qs = (HorecaOrder.objects
          .filter(is_draft=False)
          .exclude(status=HorecaOrder.Status.AVBESTILT)
          .select_related('company')
          .prefetch_related('lines'))

    if order_number:
        qs = qs.filter(order_number=order_number)
    else:
        try:
            day = datetime.strptime(raw, '%Y-%m-%d').date() if raw else timezone.localdate()
        except ValueError:
            return Response({'detail': 'Ugyldig dato.'},
                            status=http.HTTP_400_BAD_REQUEST)
        qs = qs.filter(delivery_date=day)

    qs = qs.order_by('delivery_window', 'delivery_postal_code', 'order_number')

    return Response([
        {
            'order_number': o.order_number,
            'company': o.company_name,
            'delivery_date': o.delivery_date,
            'window': o.delivery_window_label,
            'recipient': o.delivery_recipient,
            'label': o.delivery_label,
            'address': f'{o.delivery_street}, {o.delivery_postal_code} {o.delivery_city}',
            'contact_name': o.delivery_contact_name,
            # K-54 names this explicitly — the driver cannot deliver without it.
            'contact_phone': o.delivery_contact_phone,
            'instructions': o.delivery_instructions,
            'production_note': o.production_note,
            'trays': o.tray_count,
            'lines': [
                {
                    'product': line.product_name,
                    'trays': line.tray_count,
                    'pieces': line.piece_count,
                    'with_logo': line.with_logo,
                    'logo_name': line.logo_name,
                    # The snapshot, so a printed label reproduces what was true
                    # when the order was placed (K-15).
                    'allergens': line.allergens_snapshot,
                }
                for line in o.lines.all()
            ],
        }
        for o in qs
    ])


# ── Logo bundle for a production day (K-55) ─────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_horeca_day_logos(request):
    """Every logo that must be printed on a given day, as one ZIP.

    Built into a temporary file rather than a BytesIO: at 25 MB per logo an
    in-memory archive can take out a gunicorn worker, and the tempfile version
    is the same amount of code.

    Filenames carry the order number, which is what K-55 asks for — the print
    shop sorts by it.
    """
    raw = request.query_params.get('date')
    try:
        day = datetime.strptime(raw, '%Y-%m-%d').date() if raw else timezone.localdate()
    except ValueError:
        return Response({'detail': 'Ugyldig dato.'}, status=http.HTTP_400_BAD_REQUEST)

    lines = (HorecaOrderLine.objects
             .filter(order__delivery_date=day, order__is_draft=False,
                     with_logo=True, logo__isnull=False)
             .exclude(order__status=HorecaOrder.Status.AVBESTILT)
             .select_related('order', 'logo'))

    if not lines:
        return Response({'detail': f'Ingen logoer å trykke {day}.'},
                        status=http.HTTP_404_NOT_FOUND)

    tmp = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
    seen: dict[str, list[str]] = {}
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as archive:
        for line in lines:
            logo = line.logo
            # One logo used by three orders ships once, named for all three —
            # printing the same sheet three times is waste, not safety.
            key = logo.checksum_sha256
            seen.setdefault(key, []).append(
                f'{line.order.order_number}x{line.tray_count}'
            )
            if len(seen[key]) > 1:
                continue
            ext = Path(logo.original_filename or '').suffix or f'.{logo.detected_format}'
            safe_company = slugify(line.order.company_name) or 'bedrift'
            safe_logo = slugify(logo.name) or 'logo'
            name = f'{line.order.order_number}__{safe_company}__{safe_logo}{ext}'
            try:
                with logo.file.open('rb') as fh:
                    archive.writestr(name, fh.read())
            except Exception:
                log.exception('could not add logo %s to the day bundle', logo.pk)

        # A manifest, so the print shop knows how many sheets each file needs.
        manifest = '\n'.join(
            f'{key[:8]}  {", ".join(orders)}' for key, orders in seen.items()
        )
        archive.writestr('ordrer.txt',
                         f'Logoer til produksjon {day}\n\n{manifest}\n')

    tmp.close()
    response = FileResponse(open(tmp.name, 'rb'), as_attachment=True,
                            filename=f'horeca-logoer-{day}.zip',
                            content_type='application/zip')
    response['X-Content-Type-Options'] = 'nosniff'
    return response
