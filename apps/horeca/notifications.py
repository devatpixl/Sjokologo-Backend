"""Order e-mails, sent exactly once.

The consumer equivalent (`apps/orders/notifications.py`) is only ever reached
from the Vipps webhook, so a non-Vipps order mails nobody at all. HORECA never
touches Vipps, so this is its own path — but the idempotency trick is worth
copying verbatim, because a send call can be reached more than once and a
customer who gets two confirmations for one order assumes they ordered twice.
"""
import logging

from django.utils import timezone as djtz

from apps.emails import (
    send_admin_new_horeca_order_email,
    send_horeca_order_received_email,
    send_horeca_order_status_email,
)

from .models import HorecaOrder

log = logging.getLogger(__name__)


def send_horeca_order_emails_once(order: HorecaOrder) -> bool:
    """Confirmation to the customer plus the ops heads-up, at most once."""
    claimed = HorecaOrder.objects.filter(
        pk=order.pk, confirmation_emails_sent_at__isnull=True,
    ).update(confirmation_emails_sent_at=djtz.now())
    if not claimed:
        return False

    order.refresh_from_db()

    # Each wrapped separately: a Gmail hiccup on the ops copy must not cost the
    # customer their confirmation, and neither can undo an order that is
    # already committed. The claim is deliberately not rolled back, so a
    # failure here does not become a retry storm.
    for fn in (send_horeca_order_received_email, send_admin_new_horeca_order_email):
        try:
            fn(order)
        except Exception:
            log.exception('%s crashed for %s', fn.__name__, order.order_number)
    return True


def send_status_change_email(order: HorecaOrder) -> None:
    """K-49 — one mail per real transition. Internal states send nothing."""
    try:
        send_horeca_order_status_email(order)
    except Exception:
        log.exception('horeca status email crashed for %s', order.order_number)
