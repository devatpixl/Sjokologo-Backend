"""Order-flow emails: confirmation (#3), admin (#4), packing (#5),
shipped (#6), delivered (#7).
"""

from __future__ import annotations

from decimal import Decimal
from html import escape

from django.conf import settings

from .layout import (
    render_items_table,
    render_kv_block,
    render_layout,
    render_status_box,
)
from .transactional import send


# ── Helpers ────────────────────────────────────────────────────────────────

def _first_name(order) -> str:
    raw = (order.ship_first_name or '').strip()
    return raw if raw else 'der'


def _fmt_nok(value) -> str:
    """Format a Decimal/int/float NOK amount as '349 kr' or '1 250 kr'."""
    if value is None:
        return '0 kr'
    amount = Decimal(value).quantize(Decimal('1'))
    # Norwegian thousands separator is a non-breaking space.
    s = f'{int(amount):,}'.replace(',', ' ')
    return f'{s} kr'


def _shipping_label(order) -> str:
    return dict(order.SHIPPING_METHOD_CHOICES).get(
        order.shipping_method or '', 'Ikke valgt'
    )


def _shipping_detail_lines(order) -> list[tuple[str, str]]:
    """Address / pickup-point detail rows for the order confirmation block."""
    rows: list[tuple[str, str]] = []
    full_name = f'{order.ship_first_name} {order.ship_last_name}'.strip()
    rows.append(('Navn', full_name))
    rows.append(('Telefon', order.ship_phone or '—'))
    rows.append(('E-post', order.ship_email or '—'))
    if order.shipping_method in ('bring-pickup-point', 'postnord-locker'):
        rows.append(('Leveringsmetode', _shipping_label(order)))
        if order.pickup_point_name:
            rows.append(('Hentested', order.pickup_point_name))
        pickup_addr_bits = [
            order.pickup_point_address1,
            (
                f'{order.pickup_point_postcode or ""} '
                f'{order.pickup_point_city or ""}'
            ).strip(),
        ]
        pickup_addr = ', '.join(b for b in pickup_addr_bits if b)
        if pickup_addr:
            rows.append(('Adresse', pickup_addr))
    elif order.shipping_method == 'self-pickup':
        rows.append(('Leveringsmetode', _shipping_label(order)))
    else:
        rows.append(('Leveringsmetode', _shipping_label(order)))
        street = order.ship_address or '—'
        rows.append(('Adresse', street))
        rows.append((
            'Sted',
            f'{order.ship_postal_code} {order.ship_city}'.strip() or '—',
        ))
    return rows


def _payment_label(order) -> str:
    method = dict(order.PAYMENT_CHOICES).get(order.payment_method, order.payment_method or '—')
    status = dict(order.PAYMENT_STATUS_CHOICES).get(order.payment_status, order.payment_status)
    return f'{method} ({status})'


def _items_for_template(order) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    for item in order.items.all().select_related('product'):
        name = item.product.name if item.product_id else '(slettet produkt)'
        if item.variant:
            name = f'{name} — {item.variant}'
        line_total = _fmt_nok(Decimal(item.unit_price) * item.quantity)
        rows.append((name, item.quantity, line_total))
    return rows


def _totals_for_template(order) -> list[tuple[str, str]]:
    totals: list[tuple[str, str]] = [
        ('Delsum', _fmt_nok(order.subtotal)),
    ]
    if Decimal(order.discount_amount or 0) > 0:
        code = f' ({order.coupon_code})' if order.coupon_code else ''
        totals.append((f'Rabatt{code}', f'− {_fmt_nok(order.discount_amount)}'))
    totals.append(('Frakt', _fmt_nok(order.shipping)))
    totals.append(('Totalt', _fmt_nok(order.total)))
    return totals


# ── #3 Order confirmation (customer) ───────────────────────────────────────

def send_order_confirmation_email(order) -> bool:
    storefront = 'https://sjokoloco.no'
    first = _first_name(order)
    subject = f'Ordrebekreftelse — #{order.order_number}'

    item_lines = '\n'.join(
        f'  • {name}  × {qty}  →  {line_total}'
        for name, qty, line_total in _items_for_template(order)
    )
    total_lines = '\n'.join(f'  {k}: {v}' for k, v in _totals_for_template(order))
    addr_lines = '\n'.join(f'  {k}: {v}' for k, v in _shipping_detail_lines(order))

    text = (
        f'Hei, {first}!\n\n'
        'Vi har mottatt bestillingen din hos Sjoko Loco. '
        'Du får ny beskjed på e-post når vi begynner å pakke den.\n\n'
        f'Ordrenummer: {order.order_number}\n'
        f'Bestilt: {order.created_at:%d.%m.%Y %H:%M}\n\n'
        f'— Innhold —\n{item_lines}\n\n'
        f'— Beløp —\n{total_lines}\n\n'
        f'— Levering —\n{addr_lines}\n\n'
        f'Spørsmål? Bare svar på denne e-posten.\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Vi har mottatt bestillingen din hos Sjoko Loco.</p>'
        '<p style="margin:0;">Du får ny beskjed på e-post når vi begynner å pakke den.</p>'
    )

    blocks = (
        render_items_table(_items_for_template(order), _totals_for_template(order))
        + render_kv_block('◈ Leveringsdetaljer', _shipping_detail_lines(order))
    )

    confirmation_url = f'{storefront}/takk?order={order.order_number}'
    html = render_layout(
        eyebrow='◈ Ordrebekreftelse',
        heading=f'Takk for bestillingen, {first}!',
        intro_html=intro_html,
        blocks_html=blocks,
        cta_url=confirmation_url,
        cta_label='Se bestillingen',
        footer_lines=[
            f'Ordrenummer: {order.order_number}',
            f'Bestilt: {order.created_at:%d.%m.%Y %H:%M}',
        ],
    )

    return send(
        to=order.ship_email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='order_confirmation',
    )


# ── #4 Admin: new order (internal) ─────────────────────────────────────────

def send_admin_new_order_email(order) -> bool:
    recipients = [r.strip() for r in (settings.ADMIN_NOTIFY_EMAILS or []) if r.strip()]
    if not recipients:
        return False

    admin_url = (settings.ADMIN_URL or '').rstrip('/')
    full_name = f'{order.ship_first_name} {order.ship_last_name}'.strip() or '(uten navn)'
    order_link = f'{admin_url}/orders/{order.order_number}' if admin_url else ''

    subject = (
        f'Ny ordre #{order.order_number} — {_fmt_nok(order.total)} — {full_name}'
    )

    item_lines = '\n'.join(
        f'  • {name}  × {qty}  →  {line_total}'
        for name, qty, line_total in _items_for_template(order)
    )

    text = (
        f'Ny ordre på sjokoloco.no.\n\n'
        f'Nummer:   {order.order_number}\n'
        f'Bestilt:  {order.created_at:%d.%m.%Y %H:%M}\n'
        f'Beløp:    {_fmt_nok(order.total)} (delsum {_fmt_nok(order.subtotal)}, frakt {_fmt_nok(order.shipping)})\n'
        f'Betaling: {_payment_label(order)}\n\n'
        f'Kunde\n'
        f'  Navn:    {full_name}\n'
        f'  E-post:  {order.ship_email}\n'
        f'  Telefon: {order.ship_phone}\n\n'
        f'Levering\n'
        f'  Metode:  {_shipping_label(order)}\n'
        f'  Adresse: {order.ship_address}, {order.ship_postal_code} {order.ship_city}\n\n'
        f'Innhold\n{item_lines}\n'
        + (f'\nÅpne i admin: {order_link}\n' if order_link else '')
    )

    intro_html = (
        f'<p style="margin:0;">En ny ordre er kommet inn. '
        f'Total: <strong>{escape(_fmt_nok(order.total))}</strong>.</p>'
    )

    kv_rows = [
        ('Ordrenummer', order.order_number),
        ('Bestilt', f'{order.created_at:%d.%m.%Y %H:%M}'),
        ('Beløp', _fmt_nok(order.total)),
        ('Betaling', _payment_label(order)),
        ('Kunde', full_name),
        ('E-post', order.ship_email),
        ('Telefon', order.ship_phone),
        ('Leveringsmetode', _shipping_label(order)),
    ]

    blocks = (
        render_kv_block('◈ Ordreinfo', kv_rows)
        + render_items_table(_items_for_template(order), _totals_for_template(order))
    )

    html = render_layout(
        eyebrow='◈ Intern varsling',
        heading=f'Ny ordre #{order.order_number}',
        intro_html=intro_html,
        blocks_html=blocks,
        cta_url=order_link or None,
        cta_label='Åpne ordre i admin' if order_link else None,
        closing_html=(
            '<p style="margin:0; font-size:12px; color:rgba(245,239,230,0.55);">'
            'Sendt automatisk fra Sjoko Loco-API</p>'
        ),
    )

    return send(
        to=recipients,
        subject=subject,
        text_body=text,
        html_body=html,
        label='admin_new_order',
    )


# ── #5 Packing (customer) ──────────────────────────────────────────────────

def send_order_packing_email(order) -> bool:
    first = _first_name(order)
    subject = f'Vi pakker bestillingen din — #{order.order_number}'

    text = (
        f'Hei, {first}!\n\n'
        'Bestillingen din pakkes nå hos oss i Ås.\n\n'
        'Du får en ny e-post med sporingsnummer så snart pakken er på vei.\n\n'
        f'Ordrenummer: {order.order_number}\n'
        f'Leveringsmetode: {_shipping_label(order)}\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Bestillingen din pakkes nå hos oss i Ås.</p>'
        '<p style="margin:0;">Du får en ny e-post med sporingsnummer '
        'så snart pakken er på vei.</p>'
    )

    blocks = render_status_box('◈ Status', 'Pakkes')

    html = render_layout(
        eyebrow='◈ Status: Pakkes',
        heading='Bestillingen din pakkes nå',
        intro_html=intro_html,
        blocks_html=blocks,
        footer_lines=[
            f'Ordrenummer: {order.order_number}',
            f'Leveringsmetode: {_shipping_label(order)}',
        ],
    )

    return send(
        to=order.ship_email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='order_packing',
    )


# ── #6 Shipped (customer) ──────────────────────────────────────────────────

def send_order_shipped_email(order) -> bool:
    first = _first_name(order)
    carrier_label = _shipping_label(order)
    tracking_url = (order.tracking_url or '').strip()
    consignment = (order.consignment_number or '').strip()

    subject = f'Bestillingen er sendt — sporing inkludert (#{order.order_number})'

    tracking_text = (
        f'Sporingslenke: {tracking_url}\n'
        if tracking_url else
        'Sporingslenke kommer så snart fraktselskapet har registrert pakken.\n'
    )

    pickup_text = ''
    if order.shipping_method in ('bring-pickup-point', 'postnord-locker') and order.pickup_point_name:
        pickup_text = (
            f'\nHentested: {order.pickup_point_name}\n'
            f'  {order.pickup_point_address1 or ""}, '
            f'{order.pickup_point_postcode or ""} {order.pickup_point_city or ""}\n'
        )

    text = (
        f'Hei, {first}!\n\n'
        f'Bestillingen din er nå sendt med {carrier_label}. '
        'Du kan følge pakken hele veien fram med sporingslenken under.\n\n'
        + (f'Sporingsnummer: {consignment}\n' if consignment else '')
        + tracking_text
        + pickup_text
        + f'\nOrdrenummer: {order.order_number}\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        f'<p style="margin:0 0 12px;">Bestillingen din er nå sendt med '
        f'<strong>{escape(carrier_label)}</strong>.</p>'
        '<p style="margin:0;">Du kan følge pakken hele veien fram med sporingslenken under.</p>'
    )

    blocks_html = ''
    if consignment:
        blocks_html += render_status_box('◈ Sporingsnummer', consignment)
    if order.shipping_method in ('bring-pickup-point', 'postnord-locker') and order.pickup_point_name:
        pickup_rows = [
            ('Hentested', order.pickup_point_name),
            (
                'Adresse',
                f'{order.pickup_point_address1 or ""}, '
                f'{order.pickup_point_postcode or ""} {order.pickup_point_city or ""}'.strip(', '),
            ),
        ]
        blocks_html += render_kv_block('◈ Hentepunkt', pickup_rows)

    html = render_layout(
        eyebrow='◈ Status: Sendt',
        heading='Pakken er på vei!',
        intro_html=intro_html,
        blocks_html=blocks_html,
        cta_url=tracking_url or None,
        cta_label='Spor pakken' if tracking_url else None,
        footer_lines=[
            f'Ordrenummer: {order.order_number}',
            f'Leveringsmetode: {carrier_label}',
        ],
    )

    return send(
        to=order.ship_email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='order_shipped',
    )


# ── #7 Delivered (customer) ────────────────────────────────────────────────

def send_order_delivered_email(order) -> bool:
    storefront = 'https://sjokoloco.no'
    first = _first_name(order)
    subject = f'Takk for bestillingen — håper det smaker! (#{order.order_number})'

    text = (
        f'Hei, {first}!\n\n'
        'Pakken din er levert — vi håper det smaker.\n\n'
        'Har du tilbakemeldinger eller spørsmål? Bare svar på denne e-posten — vi leser alle.\n\n'
        f'Handle igjen: {storefront}\n\n'
        f'Ordrenummer: {order.order_number}\n\n'
        'Hilsen\n'
        'Team Sjoko Loco'
    )

    intro_html = (
        '<p style="margin:0 0 12px;">Pakken din er levert — vi håper det smaker.</p>'
        '<p style="margin:0;">Har du tilbakemeldinger eller spørsmål? '
        'Bare svar på denne e-posten — vi leser alle.</p>'
    )

    blocks = render_status_box('◈ Status', 'Levert')

    html = render_layout(
        eyebrow='◈ Levert',
        heading=f'Velbekomme, {first}!',
        intro_html=intro_html,
        blocks_html=blocks,
        cta_url=storefront,
        cta_label='Handle igjen',
        footer_lines=[f'Ordrenummer: {order.order_number}'],
    )

    return send(
        to=order.ship_email,
        subject=subject,
        text_body=text,
        html_body=html,
        label='order_delivered',
    )
