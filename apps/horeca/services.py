"""Order lifecycle. Everything that writes a HorecaOrder goes through here.

Two things in this module are load-bearing and easy to lose:

1. `recalculate_order()` is the ONLY place `tray_count` and the money columns
   are computed. `tray_count` is denormalised so the capacity question is one
   indexed Sum — which means any path that touches lines and forgets to
   recalculate silently corrupts the calendar for every other customer.
2. `lock_delivery_day()` is what makes the capacity check real. The calendar is
   advisory: two customers can both be shown "5 trays left" and both book 5.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection, transaction
from django.utils import timezone as djtz
from rest_framework.exceptions import ValidationError

from .availability import availability, first_available_date
from .models import (
    HorecaOrder,
    HorecaOrderEvent,
    HorecaOrderLine,
    HorecaProduct,
    HorecaSettings,
    Logo,
)
from .numbering import next_horeca_order_number
from .pricing import resolve_unit_price

# Arbitrary but stable namespace for the day lock.
CAPACITY_LOCK_NAMESPACE = 8471


def lock_delivery_day(day) -> None:
    """Serialise capacity checks for one delivery date.

    A transaction-scoped advisory lock rather than `SELECT ... FOR UPDATE`,
    because there is no row to lock: the first order for a given day is
    precisely the case where no record exists yet. Released at COMMIT, so
    nothing needs cleaning up. One order has one delivery date, so only one
    lock is ever held and deadlock is not possible.
    """
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(%s, %s)',
                    [CAPACITY_LOCK_NAMESPACE, day.toordinal()])


# ── building and pricing ────────────────────────────────────────────────────

@dataclass
class LineSpec:
    product: HorecaProduct
    tray_count: int
    with_logo: bool
    logo: Logo | None
    line_note: str = ''


ZERO = Decimal('0.00')
CENTS = Decimal('0.01')


def recalculate_order(order: HorecaOrder) -> HorecaOrder:
    """Recompute every derived value from the lines. Call after ANY line change.

    VAT is rounded once per line rather than once on the total: lines can carry
    different rates, and summing unrounded fractions then rounding the total
    produces a figure that does not match the sum of the printed line amounts —
    which is the kind of one-øre discrepancy an accountant will ask about.
    """
    lines = list(order.lines.all())

    order.tray_count = sum(line.tray_count for line in lines)

    subtotal = sum((line.line_total_ex_vat for line in lines), ZERO)
    vat = sum(
        (
            (line.line_total_ex_vat * line.vat_rate / Decimal(100))
            .quantize(CENTS, rounding=ROUND_HALF_UP)
            for line in lines
        ),
        ZERO,
    )

    order.subtotal_ex_vat = subtotal.quantize(CENTS, rounding=ROUND_HALF_UP)
    order.vat_amount = vat
    order.total_inc_vat = order.subtotal_ex_vat + order.vat_amount

    order.save(update_fields=[
        'tray_count', 'subtotal_ex_vat', 'vat_amount', 'total_inc_vat',
        'updated_at',
    ])
    return order


def build_line(order: HorecaOrder, spec: LineSpec, company) -> HorecaOrderLine:
    """One order line, with every snapshot the packing list and invoice need."""
    unit_price, source = resolve_unit_price(spec.product, company)
    pieces = spec.product.pieces_for(spec.with_logo)
    return HorecaOrderLine(
        order=order,
        product=spec.product,
        product_name=spec.product.name,
        product_slug=spec.product.slug,
        tray_count=spec.tray_count,
        with_logo=spec.with_logo,
        logo=spec.logo,
        logo_name=spec.logo.name if spec.logo else '',
        pieces_per_tray=pieces,
        piece_count=pieces * spec.tray_count,
        unit_price_ex_vat=unit_price,
        price_source=source,
        vat_rate=spec.product.vat_rate,
        line_total_ex_vat=unit_price * spec.tray_count,
        # K-15 — the label must reproduce what was true when the order was
        # placed, not what the product says today.
        allergens_snapshot=list(spec.product.allergens or []),
        ingredients_snapshot=spec.product.ingredients_text,
        line_note=spec.line_note,
    )


def snapshot_address(order: HorecaOrder, address) -> None:
    """K-38 — copy, never point.

    Editing a saved address afterwards must not rewrite an order that has
    already been produced and delivered. The FK is kept only as a breadcrumb
    for "reorder to the same place".
    """
    order.delivery_address_source = address
    order.delivery_label = address.label
    order.delivery_recipient = address.recipient
    order.delivery_contact_name = address.contact_name
    order.delivery_contact_phone = address.contact_phone
    order.delivery_street = address.street
    order.delivery_postal_code = address.postal_code
    order.delivery_city = address.city
    order.delivery_country = address.country
    order.delivery_instructions = address.instructions


def snapshot_one_off_address(order: HorecaOrder, data: dict) -> None:
    """K-35 — the same flat copy, with no saved row behind it.

    `delivery_address_source` stays NULL, which is exactly right: there is no
    saved address to point back at, and "reorder to the same place" should not
    silently resurrect a one-night venue.
    """
    order.delivery_address_source = None
    order.delivery_label = data.get('label') or 'Engangsadresse'
    order.delivery_recipient = data.get('recipient', '')
    order.delivery_contact_name = data.get('contact_name', '')
    order.delivery_contact_phone = data['contact_phone']
    order.delivery_street = data['street']
    order.delivery_postal_code = data['postal_code']
    order.delivery_city = data['city']
    order.delivery_country = 'Norge'
    order.delivery_instructions = data.get('instructions', '')


def record_event(order, *, from_status='', to_status='', actor=None,
                 source=HorecaOrderEvent.Source.SYSTEM, note=''):
    """K-50 — one row per real change, so the history is never reconstructed."""
    return HorecaOrderEvent.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        actor_name=getattr(actor, 'name', '') or '',
        source=source,
        note=note,
    )


# ── the rules that refuse an order ──────────────────────────────────────────

def validate_orderable(order: HorecaOrder, *, cfg=None) -> None:
    """Everything that must be true before a draft may be sent.

    Raises ValidationError with Norwegian messages. Called server-side on send —
    the frontend hiding a button is not a rule (K-62).
    """
    cfg = cfg or HorecaSettings.load()
    lines = list(order.lines.select_related('product', 'logo'))

    if not lines:
        raise ValidationError({'lines': 'Bestillingen er tom.'})
    if not order.delivery_date:
        raise ValidationError({'delivery_date': 'Velg en leveringsdato.'})
    if not order.delivery_window:
        raise ValidationError({'delivery_window': 'Velg et tidsvindu.'})
    if not order.delivery_street:
        raise ValidationError({'address': 'Velg en leveringsadresse.'})
    if cfg.ordering_paused:
        raise ValidationError({
            'detail': cfg.paused_message or 'Bestillinger er midlertidig stengt.',
        })

    windows = {w['code'] for w in (cfg.delivery_windows or [])}
    if order.delivery_window not in windows:
        raise ValidationError({'delivery_window': 'Ugyldig tidsvindu.'})

    total_trays = sum(line.tray_count for line in lines)
    if total_trays < cfg.min_trays_per_order:
        raise ValidationError({
            'lines': f'Minste bestilling er {cfg.min_trays_per_order} brett.',
        })
    if total_trays > cfg.max_trays_per_order:
        raise ValidationError({
            'lines': f'Maks {cfg.max_trays_per_order} brett per bestilling. '
                     'Ta kontakt for større bestillinger.',
        })

    for line in lines:
        if not line.product.is_active:
            raise ValidationError({
                'lines': f'{line.product_name} kan ikke bestilles lenger.',
            })
        # K-17
        if line.with_logo:
            if line.logo is None:
                raise ValidationError({
                    'lines': f'{line.product_name} med logo mangler logofil.',
                })
            # Cross-tenant guard. This is the check that stops one company
            # printing another company's logo.
            if line.logo.company_id != order.company_id:
                raise ValidationError({'lines': 'Ugyldig logo.'})
            if line.logo.is_archived:
                raise ValidationError({
                    'lines': f'Logoen "{line.logo.name}" er arkivert.',
                })
            # K-28 is deliberate about this: a PENDING logo is fine to order
            # against — "en bestilling kan legges inn i mellomtiden" — and it
            # is production that waits, not the customer. A REJECTED one is
            # different: we have already said we cannot print it.
            if line.logo.status == Logo.Status.REJECTED:
                raise ValidationError({'lines': (
                    f'Logoen "{line.logo.name}" er avvist. '
                    'Last opp en ny versjon før dere bestiller med logo.'
                )})
            if not line.product.logo_available:
                raise ValidationError({
                    'lines': f'{line.product_name} kan ikke trykkes med logo.',
                })

    has_logo = any(line.with_logo for line in lines)
    # K-43 — the products in THIS basket decide the lead time, not just the
    # global default. A hand-decorated tray sets the pace for the whole order.
    basket = [line.product for line in lines]
    days = availability(
        order.delivery_date, order.delivery_date,
        has_logo=has_logo, exclude_order=order.pk, cfg=cfg, products=basket,
    )
    day = days[0]
    if not day.available:
        suggestion = first_available_date(has_logo=has_logo, trays=total_trays,
                                          cfg=cfg, products=basket)
        detail = day.message
        if suggestion:
            detail += f' Første ledige dag er {suggestion.strftime("%d.%m.%Y")}.'
        raise ValidationError({'delivery_date': detail})

    if day.trays_capacity and day.trays_remaining < total_trays:
        suggestion = first_available_date(has_logo=has_logo, trays=total_trays,
                                          cfg=cfg, products=basket)
        detail = (
            f'Det er {day.trays_remaining} brett igjen denne dagen, '
            f'og bestillingen er på {total_trays}.'
        )
        if suggestion:
            detail += f' Første dag med plass er {suggestion.strftime("%d.%m.%Y")}.'
        raise ValidationError({'delivery_date': detail})


@transaction.atomic
def send_order(order: HorecaOrder, *, actor=None) -> HorecaOrder:
    """Draft → Sendt (K-19, K-20). The capacity check that actually counts."""
    if not order.is_draft:
        raise ValidationError({'detail': 'Bestillingen er allerede sendt.'})

    cfg = HorecaSettings.load()
    # Lock first, then re-check: between the customer seeing the calendar and
    # pressing send, somebody else may have taken the last trays.
    lock_delivery_day(order.delivery_date) if order.delivery_date else None
    validate_orderable(order, cfg=cfg)

    order.order_number = order.order_number or next_horeca_order_number()
    order.is_draft = False
    order.status = HorecaOrder.Status.SENDT
    order.sent_at = djtz.now()
    order.company_name = order.company.name
    order.org_number = order.company.org_number
    if actor is not None:
        order.placed_by = actor
        order.placed_by_name = actor.name or ''
        order.placed_by_email = actor.email
    order.save()

    record_event(order, to_status=order.status, actor=actor,
                 source=HorecaOrderEvent.Source.PORTAL, note='Bestilling sendt')
    return order


def has_unapproved_logo(order: HorecaOrder) -> bool:
    """K-28 — any line printed with a logo we have not approved yet.

    Derived rather than stored: a flag would go stale the moment a logo is
    approved, and the answer is one indexed query.
    """
    return (
        order.lines
        .filter(with_logo=True)
        .exclude(logo__status=Logo.Status.APPROVED)
        .exists()
    )


def assert_can_enter_production(order: HorecaOrder) -> None:
    """Refuse to start production while artwork is still unapproved.

    Enforced here rather than only shown in the admin list, because the whole
    point of the approval step is that nothing reaches the edible-sheet printer
    without a human having looked at it.
    """
    if has_unapproved_logo(order):
        names = ', '.join(
            line.logo.name for line in order.lines.select_related('logo')
            if line.with_logo and line.logo and line.logo.status != Logo.Status.APPROVED
        )
        raise ValidationError({'status': (
            f'Logoen er ikke godkjent ennå ({names}). '
            'Godkjenn den før ordren settes i produksjon.'
        )})


@transaction.atomic
def cancel_order(order: HorecaOrder, *, actor=None, reason='',
                 source=HorecaOrderEvent.Source.PORTAL) -> HorecaOrder:
    """K-45, K-48. Cancelling frees the capacity it was holding."""
    if source == HorecaOrderEvent.Source.PORTAL and not order.can_be_cancelled_by_customer():
        cfg = HorecaSettings.load()
        raise ValidationError({'detail': (
            'Fristen for å avbestille har gått ut. '
            f'Ta kontakt på {cfg.contact_phone or "telefon"} så hjelper vi deg.'
        )})

    previous = order.status
    order.status = HorecaOrder.Status.AVBESTILT
    order.cancelled_at = djtz.now()
    order.cancelled_by = actor
    order.cancellation_reason = reason
    order.save(update_fields=[
        'status', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'updated_at',
    ])
    record_event(order, from_status=previous, to_status=order.status,
                 actor=actor, source=source, note=reason)
    return order
