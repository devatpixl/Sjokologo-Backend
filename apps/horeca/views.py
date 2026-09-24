"""Customer-facing HORECA endpoints.

Every view below carries an explicit `@permission_classes`. That is not
decoration: this project sets `DEFAULT_PERMISSION_CLASSES = AllowAny`
(config/settings.py), so a view that omits it is public. `apps/orders/views.py`
already ships full order PII that way. A test walks this app's URLconf and fails
if any view here resolves to AllowAny, so the rule outlives whoever remembers it.
"""
import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone as djtz

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.emails import (
    send_admin_new_horeca_company_email,
    send_horeca_invite_email,
    send_horeca_password_reset_email,
    send_horeca_order_cancelled_email,
    send_admin_new_horeca_logo_email,
    send_horeca_logo_received_email,
    send_horeca_registration_received_email,
)
from apps.users.models import CustomUser
from apps.users.password_setup import (
    HORECA_RESET_MAX_AGE_SECONDS,
    build_horeca_password_link,
    build_password_link,
    resolve_horeca_password_token,
)

from .availability import (
    availability,
    earliest_eligible_date,
    first_available_date,
)
from .logo_validation import probe_logo
from .models import (
    HorecaOrder,
    Membership,
    HorecaOrderLine,
    HorecaProduct,
    HorecaSettings,
    Logo,
)
from .notifications import send_horeca_order_emails_once
from .permissions import (
    IsApprovedHorecaUser,
    IsHorecaUser,
    company_for_request,
    membership_for_request,
)
from .pricing import may_see_prices
from .scoping import (
    company_addresses,
    company_logos,
    company_orders,
    get_company_address,
    get_company_draft,
    get_company_logo,
    get_company_order,
)
from .services import (
    LineSpec,
    build_line,
    cancel_order,
    recalculate_order,
    send_order,
    snapshot_address,
    snapshot_one_off_address,
)
from .serializers import (
    CompanyRegisterSerializer,
    CompanySerializer,
    DeliveryAddressSerializer,
    HorecaOrderSerializer,
    HorecaProductSerializer,
    LogoSerializer,
    MemberInviteSerializer,
    OrderWriteSerializer,
    MembershipSerializer,
)

log = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def horeca_register_view(request):
    if not settings.HORECA_SELF_REGISTRATION:
        # 403 rather than 404: the route exists and is coming back. Saying so
        # plainly is what stops a chef concluding the site is broken and gives
        # them the one action that does work — phoning us.
        return Response(
            {'detail': 'Bedriftskontoer opprettes av Sjoko Loco. '
                       'Ta kontakt, så setter vi opp kontoen for dere.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    """K-5 — register a business. Lands as 'venter godkjenning'."""
    serializer = CompanyRegisterSerializer(data=request.data, context={})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    company = serializer.save()
    user = serializer.context['user']
    needs_password = serializer.context['needs_password']

    # Best-effort, exactly as consumer signup does it: an SMTP blip must never
    # undo an account that is already committed.
    try:
        send_horeca_registration_received_email(
            user,
            company,
            # Anyone without a usable password needs the link — that is a
            # brand-new account, and also a guest-checkout shell, which has a
            # row but no way to sign in.
            password_url=build_password_link(user) if needs_password else None,
        )
    except Exception:
        log.exception('horeca registration email crashed for %s', user.email)

    # K-57 — tell Sjoko Loco someone is waiting. Separate try block on purpose:
    # a failure here must not stop the customer's own mail from having been sent,
    # and vice versa.
    try:
        send_admin_new_horeca_company_email(company)
    except Exception:
        log.exception('horeca admin notification crashed for %s', company.pk)

    # No tokens returned. A new account has no password yet, so they sign in
    # after following the link — the same contract as consumer registration.
    return Response(
        {
            'detail': 'created',
            'email': user.email,
            'company_status': company.status,
            'needs_password': needs_password,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_me_view(request):
    """Who am I, which company, what may I do — the portal's bootstrap call."""
    membership = membership_for_request(request)
    company = membership.company
    return Response({
        'company': CompanySerializer(company).data,
        'membership': MembershipSerializer(membership).data,
        # K-6 in one boolean, so the frontend never has to re-derive the rule.
        'can_order': company.can_order,
    })


# ── Catalogue (K-11 … K-15) ─────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_product_list_view(request):
    """The varebok. Browsable before approval; prices are not (K-6)."""
    company = company_for_request(request)
    products = HorecaProduct.objects.filter(is_active=True)
    return Response(HorecaProductSerializer(
        products, many=True,
        context={'request': request, 'show_prices': may_see_prices(company)},
    ).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_product_detail_view(request, slug):
    company = company_for_request(request)
    product = get_object_or_404(HorecaProduct, slug=slug, is_active=True)
    return Response(HorecaProductSerializer(
        product,
        context={'request': request, 'show_prices': may_see_prices(company)},
    ).data)


# ── Availability calendar (K-39 … K-45) ─────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_availability_view(request):
    """Which days can be delivered on, and why not when not.

    `reason` and `message` are always present for a blocked day — K-44 is a
    requirement about words, and a greyed-out cell with no explanation is the
    single most likely thing to be quietly skipped.
    """
    cfg = HorecaSettings.load()
    today = djtz.localdate()
    has_logo = str(request.query_params.get('has_logo', '')).lower() in ('1', 'true', 'ja')
    trays = max(int(request.query_params.get('trays') or 1), 1)

    # K-43 — the calendar must reflect the basket, not just the defaults.
    slugs = [s for s in (request.query_params.get('products') or '').split(',') if s]
    basket = list(HorecaProduct.objects.filter(slug__in=slugs)) if slugs else None

    start = _parse_date(request.query_params.get('from')) or today
    end = _parse_date(request.query_params.get('to')) or (start + timedelta(days=62))
    # Cap the window so a stray ?to=2099-01-01 cannot ask for 27,000 rows.
    end = min(end, today + timedelta(days=cfg.order_horizon_days))
    if end < start:
        end = start

    days = availability(start, end, has_logo=has_logo, cfg=cfg, products=basket)
    suggestion = first_available_date(has_logo=has_logo, trays=trays, cfg=cfg,
                                      products=basket)

    return Response({
        'earliest_date': earliest_eligible_date(has_logo=has_logo, cfg=cfg,
                                                products=basket),
        'first_available_date': suggestion,
        'windows': cfg.delivery_windows,
        'max_trays_per_day': cfg.max_trays_per_day,
        'cancel_deadline_days': cfg.cancel_deadline_days,
        'contact_phone': cfg.contact_phone,
        'days': [
            {
                'date': d.date,
                'available': d.available,
                'reason': d.reason,
                'message': d.message,
                'trays_remaining': d.trays_remaining,
            }
            for d in days
        ],
    })


def _parse_date(raw):
    if not raw:
        return None
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


# ── Delivery addresses (K-33 … K-38) ────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_address_list_view(request):
    company = company_for_request(request)

    if request.method == 'GET':
        return Response(DeliveryAddressSerializer(
            company_addresses(company), many=True,
        ).data)

    serializer = DeliveryAddressSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        _clear_default_if_needed(company, serializer.validated_data)
        address = serializer.save(company=company)
    return Response(DeliveryAddressSerializer(address).data,
                    status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_address_detail_view(request, pk):
    company = company_for_request(request)
    address = get_company_address(company, pk)

    if request.method == 'GET':
        return Response(DeliveryAddressSerializer(address).data)

    if request.method == 'DELETE':
        # K-38 — archived, never deleted. Orders keep a copy of the address, but
        # the breadcrumb FK must stay resolvable and history must not change.
        address.is_archived = True
        address.is_default = False
        address.save(update_fields=['is_archived', 'is_default', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = DeliveryAddressSerializer(address, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        _clear_default_if_needed(company, serializer.validated_data, exclude=address.pk)
        serializer.save()
    return Response(serializer.data)


def _clear_default_if_needed(company, data, exclude=None):
    """Only one default per company, and Postgres enforces it with a partial
    unique index — so the old default must be cleared BEFORE the new one is
    set, or the insert raises IntegrityError."""
    if not data.get('is_default'):
        return
    qs = company_addresses(company).filter(is_default=True)
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    qs.update(is_default=False)


# ── Logos (K-24 … K-32) ─────────────────────────────────────────────────────

LOGO_URL_SALT = 'horeca-logo-file'
LOGO_URL_MAX_AGE = 300  # seconds


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_logo_list_view(request):
    company = company_for_request(request)

    if request.method == 'GET':
        return Response(LogoSerializer(company_logos(company), many=True).data)

    upload = request.FILES.get('file')
    if upload is None:
        return Response({'file': 'Velg en fil.'}, status=status.HTTP_400_BAD_REQUEST)

    # Content-based validation. Raises ValidationError with a message that says
    # what to do about it.
    probe = probe_logo(upload)

    # K-29 follow-through: re-uploading the exact file that was just rejected
    # should get the original reason back, not a second pending review.
    clash = company_logos(company, include_archived=True).filter(
        checksum_sha256=probe.checksum_sha256, status=Logo.Status.REJECTED,
    ).first()
    if clash is not None:
        return Response({'file': (
            'Denne filen er allerede vurdert og avvist. '
            f'{clash.rejection_reason or ""}'.strip()
        )}, status=status.HTTP_400_BAD_REQUEST)

    logo = Logo.objects.create(
        company=company,
        name=(request.data.get('name') or upload.name or 'Logo')[:120],
        file=upload,
        original_filename=(upload.name or '')[:255],
        detected_format=probe.detected_format,
        kind=probe.kind,
        content_type=getattr(upload, 'content_type', '') or '',
        byte_size=probe.byte_size,
        checksum_sha256=probe.checksum_sha256,
        width_px=probe.width_px,
        height_px=probe.height_px,
        uploaded_by=request.user,
    )

    for fn, arg in (
        (send_horeca_logo_received_email, request.user),
        (send_admin_new_horeca_logo_email, None),
    ):
        try:
            fn(arg, logo) if arg is not None else fn(logo)
        except Exception:
            log.exception('horeca logo email crashed for %s', logo.pk)

    return Response(LogoSerializer(logo).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_logo_detail_view(request, pk):
    company = company_for_request(request)
    logo = get_company_logo(company, pk)

    if request.method == 'GET':
        return Response(LogoSerializer(logo).data)

    if request.method == 'DELETE':
        # Never a hard delete: order lines PROTECT the logo, so a real delete
        # would raise on any logo that has ever been ordered (K-32).
        logo.is_archived = True
        logo.save(update_fields=['is_archived', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    name = request.data.get('name')
    if name:
        logo.name = str(name)[:120]
        logo.save(update_fields=['name', 'updated_at'])
    return Response(LogoSerializer(logo).data)


def _stream_logo(logo):
    """Always as an attachment, never inline.

    An SVG served inline from our own origin is a scripting vector, so the
    content type is deliberately flattened for every vector format rather than
    trusting the file.
    """
    inline_safe = logo.detected_format in ('png', 'jpeg')
    content_type = logo.content_type if inline_safe else 'application/octet-stream'
    response = FileResponse(
        logo.file.open('rb'),
        as_attachment=True,
        filename=logo.original_filename or f'{logo.name}.{logo.detected_format}',
        content_type=content_type,
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_logo_file_view(request, pk):
    """Download. Scoped in the lookup, so another company's logo 404s."""
    company = company_for_request(request)
    return _stream_logo(get_company_logo(company, pk))


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_logo_signed_url_view(request, pk):
    """A short-lived URL the browser can put in an <img src>.

    An <img> tag cannot carry an Authorization header, and the preview is
    browser-side by design, so the alternative would be making the file public.
    Same mechanism the project already uses for the Vipps OIDC state cookie:
    django.core.signing with a salt and an explicit max_age.
    """
    company = company_for_request(request)
    logo = get_company_logo(company, pk)
    token = signing.dumps({'logo': str(logo.pk)}, salt=LOGO_URL_SALT)
    # Absolute, not a bare path. The storefront runs on a different origin to
    # this API, so a relative URL in an <img src> resolves against the Next.js
    # host and 404s — silently, because a broken image logs nothing useful.
    return Response({
        'url': request.build_absolute_uri(
            reverse('horeca-logo-token-file', args=[token])
        ),
        'expires_in': LOGO_URL_MAX_AGE,
    })


@api_view(['GET'])
@permission_classes([AllowAny])
def horeca_logo_token_file_view(request, token):
    """Token-gated, not open: the signature IS the authorisation, and it
    expires in five minutes."""
    try:
        data = signing.loads(token, salt=LOGO_URL_SALT, max_age=LOGO_URL_MAX_AGE)
    except signing.BadSignature:
        raise Http404
    logo = get_object_or_404(Logo, pk=data.get('logo'))  # unscoped-ok: the signed token IS the authorisation, and there is no session here to scope by
    response = FileResponse(
        logo.file.open('rb'),
        content_type=(logo.content_type if logo.detected_format in ('png', 'jpeg')
                      else 'application/octet-stream'),
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=300'
    return response


# ── Orders (K-16 … K-23, K-45, K-50, K-51) ──────────────────────────────────

def _apply_order_payload(order, data, company):
    """Write a draft's lines and delivery details from validated input.

    Replaces the lines wholesale rather than diffing: a draft is small, and a
    diff here would be the second place line prices are decided. Prices are
    always resolved server-side — a client-supplied price is ignored entirely.
    """
    cfg = HorecaSettings.load()

    if 'delivery_date' in data:
        order.delivery_date = data['delivery_date']
    if data.get('delivery_window'):
        order.delivery_window = data['delivery_window']
        label = next(
            (w['label'] for w in (cfg.delivery_windows or [])
             if w['code'] == data['delivery_window']),
            data['delivery_window'],
        )
        order.delivery_window_label = label
    if 'production_note' in data:
        order.production_note = data['production_note']

    if data.get('address'):
        snapshot_address(order, get_company_address(company, data['address']))
    elif data.get('one_off_address'):
        snapshot_one_off_address(order, data['one_off_address'])

    order.save()

    specs = []
    for raw in data['lines']:
        product = get_object_or_404(
            HorecaProduct, slug=raw['product'], is_active=True,
        )
        logo = None
        if raw.get('with_logo'):
            if not raw.get('logo'):
                raise ValidationError({'lines': (
                    f'{product.name} med logo mangler logofil.'
                )})
            # Scoped lookup — this is what stops one company referencing
            # another's logo by guessing an id.
            logo = get_company_logo(company, raw['logo'])
        specs.append(LineSpec(
            product=product,
            tray_count=raw['tray_count'],
            with_logo=bool(raw.get('with_logo')),
            logo=logo,
            line_note=raw.get('line_note', ''),
        ))

    order.lines.all().delete()
    HorecaOrderLine.objects.bulk_create(
        [build_line(order, spec, company) for spec in specs]
    )
    return recalculate_order(order)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_order_list_view(request):
    company = company_for_request(request)

    if request.method == 'GET':
        # K-51 — the whole company's orders, not just your own.
        # Events as well as lines: the serializer has always included them, so
        # without this the list costs one extra query per order, and the
        # dashboard's activity feed reads them on every page load.
        qs = company_orders(company).prefetch_related('lines', 'events')
        if request.query_params.get('status'):
            qs = qs.filter(status=request.query_params['status'])
        if request.query_params.get('drafts') == 'only':
            qs = qs.filter(is_draft=True)
        elif request.query_params.get('drafts') != 'include':
            qs = qs.filter(is_draft=False)
        date_from = _parse_date(request.query_params.get('from'))
        date_to = _parse_date(request.query_params.get('to'))
        if date_from:
            qs = qs.filter(delivery_date__gte=date_from)
        if date_to:
            qs = qs.filter(delivery_date__lte=date_to)
        return Response(HorecaOrderSerializer(qs, many=True).data)

    serializer = OrderWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        order = HorecaOrder.objects.create(
            company=company,
            placed_by=request.user,
            placed_by_name=request.user.name or '',
            placed_by_email=request.user.email,
            company_name=company.name,
            org_number=company.org_number,
        )
        _apply_order_payload(order, serializer.validated_data, company)
    return Response(HorecaOrderSerializer(order).data,
                    status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_order_detail_view(request, order_number):
    company = company_for_request(request)
    order = get_company_order(company, order_number)

    if request.method == 'GET':
        return Response(HorecaOrderSerializer(order).data)

    if not order.is_draft:
        return Response(
            {'detail': 'En sendt bestilling kan ikke endres her. '
                       'Avbestill den, eller ta kontakt.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    serializer = OrderWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        _apply_order_payload(order, serializer.validated_data, company)
    return Response(HorecaOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsApprovedHorecaUser])
def horeca_order_send_view(request, pk):
    """Draft → Sendt. IsApprovedHorecaUser is K-6 enforced server-side —
    the browsing endpoints deliberately use the weaker class."""
    company = company_for_request(request)
    order = get_company_draft(company, pk)
    order = send_order(order, actor=request.user)

    # on_commit so a rolled-back send never mails. The consumer path fires its
    # mail inline and has the opposite problem.
    transaction.on_commit(lambda: send_horeca_order_emails_once(order))
    return Response(HorecaOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_order_cancel_view(request, order_number):
    """K-45 / K-48 — allowed until the deadline, never once production started."""
    company = company_for_request(request)
    order = get_company_order(company, order_number)
    order = cancel_order(
        order, actor=request.user,
        reason=(request.data.get('reason') or '').strip(),
    )
    try:
        send_horeca_order_cancelled_email(order)
    except Exception:
        log.exception('horeca cancellation email crashed for %s', order.order_number)
    return Response(HorecaOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_order_repeat_view(request, order_number):
    """K-21 — the commonest order a regular customer places.

    Copies an existing order into a fresh draft: same products, same quantities,
    same logos, no date. Prices are re-resolved rather than copied, so a repeat
    never quietly charges last year's price.
    """
    company = company_for_request(request)
    source = get_company_order(company, order_number)

    with transaction.atomic():
        draft = HorecaOrder.objects.create(
            company=company,
            placed_by=request.user,
            placed_by_name=request.user.name or '',
            placed_by_email=request.user.email,
            company_name=company.name,
            org_number=company.org_number,
            production_note=source.production_note,
        )
        if source.delivery_address_source_id:
            address = company_addresses(company).filter(
                pk=source.delivery_address_source_id,
            ).first()
            if address:
                snapshot_address(draft, address)
                draft.save()

        specs = []
        for line in source.lines.select_related('product', 'logo'):
            if not line.product.is_active:
                continue  # silently drop a discontinued tray rather than 500
            logo = line.logo if (line.logo and line.logo.is_usable) else None
            specs.append(LineSpec(
                product=line.product,
                tray_count=line.tray_count,
                with_logo=bool(logo),
                logo=logo,
                line_note=line.line_note,
            ))
        if not specs:
            raise ValidationError({'detail': (
                'Ingen av brettene i denne bestillingen kan bestilles nå.'
            )})
        HorecaOrderLine.objects.bulk_create(
            [build_line(draft, spec, company) for spec in specs]
        )
        recalculate_order(draft)

    return Response(HorecaOrderSerializer(draft).data,
                    status=status.HTTP_201_CREATED)


# ── Colleagues (K-8, K-3) ───────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_member_list_view(request):
    company = company_for_request(request)

    if request.method == 'GET':
        members = (Membership.objects
                   .filter(company=company)
                   .select_related('user')
                   .order_by('-is_active', 'created_at'))
        return Response(MembershipSerializer(members, many=True).data)

    # Inviting is a bedriftsadmin act (K-8). Checked here rather than with a
    # permission class because the GET above is open to any member.
    membership = membership_for_request(request)
    if membership.role != Membership.Role.BEDRIFTSADMIN:
        return Response({'detail': 'Bare en bedriftsadmin kan invitere kolleger.'},
                        status=status.HTTP_403_FORBIDDEN)

    serializer = MemberInviteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email'].strip().lower()

    if Membership.objects.filter(company=company, user__email__iexact=email).exists():
        return Response({'email': 'Denne kollegaen har allerede tilgang.'},
                        status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        user = CustomUser.objects.filter(email__iexact=email).first()
        # Same rule as registration: a guest-checkout row is not a usable
        # account, so it still needs a password link.
        needs_password = user is None or not user.has_usable_password()
        if user is None:
            user = CustomUser.objects.create(
                email=email,
                name=serializer.validated_data.get('name', '').strip(),
                user_type='horeca',
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
        elif user.user_type == 'guest':
            user.user_type = 'horeca'
            user.save(update_fields=['user_type'])

        invite = Membership.objects.create(
            user=user,
            company=company,
            role=serializer.validated_data['role'],
            invited_by=request.user,
            invited_at=djtz.now(),
        )

    try:
        send_horeca_invite_email(
            user, company,
            inviter_name=request.user.name or '',
            password_url=build_password_link(user) if needs_password else None,
        )
    except Exception:
        log.exception('horeca invite email crashed for %s', email)

    return Response(MembershipSerializer(invite).data,
                    status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, IsHorecaUser])
def horeca_member_detail_view(request, pk):
    """K-3 — deactivate a leaver without losing the company's order history."""
    company = company_for_request(request)
    actor = membership_for_request(request)
    if actor.role != Membership.Role.BEDRIFTSADMIN:
        return Response({'detail': 'Bare en bedriftsadmin kan endre tilganger.'},
                        status=status.HTTP_403_FORBIDDEN)

    member = get_object_or_404(Membership, pk=pk, company=company)
    if member.pk == actor.pk:
        # Otherwise the last admin can lock the whole company out of its own
        # portal with one tap.
        return Response({'detail': 'Du kan ikke fjerne din egen tilgang.'},
                        status=status.HTTP_400_BAD_REQUEST)

    if 'is_active' in request.data:
        member.is_active = bool(request.data['is_active'])
    if request.data.get('role') in dict(Membership.Role.choices):
        member.role = request.data['role']
    member.save(update_fields=['is_active', 'role', 'updated_at'])
    return Response(MembershipSerializer(member).data)


# ── Password reset for the portal (K-7) ─────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def horeca_password_reset_view(request):
    """Request a 60-minute reset link.

    Always answers 200, whether or not the address exists — a different reply
    for a known address turns this endpoint into a way to enumerate which
    companies buy from Sjoko Loco. Same contract as the consumer flow.
    """
    email = (request.data.get('email') or '').strip().lower()
    user = CustomUser.objects.filter(email__iexact=email, is_active=True).first()

    if user is not None and Membership.objects.filter(
        user=user, is_active=True,
    ).exists():
        try:
            send_horeca_password_reset_email(
                user, build_horeca_password_link(user),
                minutes=HORECA_RESET_MAX_AGE_SECONDS // 60,
            )
        except Exception:
            log.exception('horeca reset email crashed for %s', email)

    return Response({'detail': 'ok'})


@api_view(['POST'])
@permission_classes([AllowAny])
def horeca_set_password_view(request):
    """Consume a reset link and set the new password."""
    token = (request.data.get('token') or '').strip()
    password = request.data.get('password') or ''

    if len(password) < 8:
        # Deliberately stricter than the consumer minimum of 6: this account
        # can place invoiced orders on a company's behalf.
        return Response({'password': 'Passordet må være minst 8 tegn.'},
                        status=status.HTTP_400_BAD_REQUEST)

    user = resolve_horeca_password_token(token)
    if user is None:
        return Response(
            {'token': 'Lenken er ugyldig eller har utløpt. Be om en ny.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user.set_password(password)
    user.save(update_fields=['password'])
    return Response({'detail': 'ok', 'email': user.email})
