"""Order e-mails, sent once the payment is approved.

Both the customer confirmation and the ops notification used to fire the
moment the order row was written, which is before Vipps has seen a payment.
That produced confirmations for orders nobody paid for (SL-00028/29) and an
ops e-mail that permanently read "Pending — no payment created yet", because
it was rendered a second before the payment existed.

They now fire from the Vipps webhook instead. ``send_order_emails_once``
claims the send with a conditional UPDATE, so duplicate or out-of-order
webhooks (AUTHORIZED and CAPTURED both call it) still send exactly one pair.
"""

from __future__ import annotations

import logging

from django.utils import timezone as djtz

from apps.emails import send_admin_new_order_email, send_order_confirmation_email

from .models import Order

log = logging.getLogger(__name__)


def send_order_emails_once(order: Order) -> bool:
    """Send the confirmation + ops pair, at most once per order.

    Returns True if this call was the one that sent them.
    """
    claimed = Order.objects.filter(
        pk=order.pk, confirmation_emails_sent_at__isnull=True,
    ).update(confirmation_emails_sent_at=djtz.now())
    if not claimed:
        return False

    order.refresh_from_db()

    # Best-effort: a Gmail hiccup must not break payment handling. The claim
    # is deliberately not rolled back, so a failure here does not turn into a
    # retry storm on every webhook redelivery.
    try:
        send_order_confirmation_email(order)
    except Exception:
        log.exception('order confirmation email crashed for %s', order.order_number)
    try:
        send_admin_new_order_email(order)
    except Exception:
        log.exception('admin new-order email crashed for %s', order.order_number)
    return True
