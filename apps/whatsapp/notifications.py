"""Ops WhatsApp alerts.

Mirrors ``apps.emails`` — same trigger point, same data, much shorter text.
Today there is exactly one alert: a "new order" ping to the shop owner, fired
from ``apps.orders.notifications.send_order_emails_once`` alongside the ops
e-mail, which means it inherits that function's guarantees: it runs only once
per order, and only after Vipps has approved the payment (so abandoned
checkouts never ping anyone).

Outbound only. Nobody replies to these, so there is no webhook and no bot.
"""
from __future__ import annotations

import logging

from django.conf import settings

from .client import send_text

log = logging.getLogger(__name__)

# WhatsApp messages are read on a phone, so keep the item list short rather
# than reproducing the whole basket — the admin link has the full picture.
MAX_ITEM_LINES = 8

# WhatsApp renders *bold*, _italic_, ~strike~ and `mono`. Values we don't
# control (product names, customer names) could contain those and silently
# reformat half the message, so strip the markers before interpolating. Only
# the literals in this module are allowed to carry formatting.
_WA_MARKUP = str.maketrans('', '', '*_~`')


def _plain(value) -> str:
    """Strip WhatsApp markup characters out of untrusted text."""
    return str(value or '').translate(_WA_MARKUP)


def _admin_chat_id() -> str:
    return str(getattr(settings, 'WHATSAPP_ADMIN_CHAT_ID', '') or '').strip()


def build_new_order_message(order) -> str:
    """Render the owner-facing 'new order' text.

    Split out from sending so it can be eyeballed in a shell without a send:
    ``build_new_order_message(Order.objects.last())``.
    """
    # Imported lazily and shared with the e-mail module on purpose: money and
    # item formatting must not drift between the two channels.
    from apps.emails.orders import _fmt_nok, _items_for_template

    full_name = _plain(f'{order.ship_first_name} {order.ship_last_name}').strip() or '(uten navn)'

    lines = [f'*Ny ordre {_plain(order.order_number)}*', '']
    lines.append(f'Beløp: {_fmt_nok(order.total)}')
    lines.append(f'Kunde: {full_name}')
    if order.ship_phone:
        lines.append(f'Tlf: {_plain(order.ship_phone)}')

    try:
        items = _items_for_template(order)
    except Exception:
        log.exception('Could not read items for order %s', order.order_number)
        items = []

    if items:
        lines.append('')
        for name, qty, _line_total in items[:MAX_ITEM_LINES]:
            lines.append(f'• {_plain(name)} × {qty}')
        remaining = len(items) - MAX_ITEM_LINES
        if remaining > 0:
            lines.append(f'… og {remaining} vare(r) til')

    admin_url = str(getattr(settings, 'ADMIN_URL', '') or '').rstrip('/')
    if admin_url:
        lines.append('')
        lines.append(f'{admin_url}/orders/{order.order_number}')

    return '\n'.join(lines)


def notify_admin_new_order(order) -> bool:
    """Ping the shop owner about a paid order. Returns True if sent."""
    chat_id = _admin_chat_id()
    if not chat_id:
        log.debug('New-order WhatsApp skipped — no admin chat id')
        return False
    return send_text(chat_id, build_new_order_message(order))
