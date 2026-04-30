"""State-machine handlers for inbound Vipps webhook events.

Each handler:
  * Runs inside the same DB transaction as the ``VippsWebhookEvent``
    idempotency-row insert (the caller wraps both in ``transaction.atomic``).
  * Locks the related Order row with ``select_for_update`` and re-reads
    state before mutating.
  * Is a no-op if the local state already reflects the event.

Out-of-order delivery (e.g. CAPTURED before AUTHORIZED) converges by
treating the more advanced state as the source of truth.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone as djtz

from apps.orders.models import Order

from .audit import record_payment_status_change
from .capture import capture_payment
from .exceptions import VippsAPIError

logger = logging.getLogger('apps.payments_vipps')


def handle_event(event_name: str, payload: dict) -> None:
    """Dispatch a webhook payload to the right state handler.

    ``event_name`` is the bare name from the payload (``AUTHORIZED``,
    ``CAPTURED``, etc.) — not the full event-type string.
    """
    handler = _DISPATCH.get(event_name)
    if handler is None:
        logger.info('vipps.webhook.ignored_event', extra={'event_name': event_name})
        return
    handler(payload)


def _get_locked_order(reference: str) -> Order | None:
    return (
        Order.objects.select_for_update()
        .filter(vipps_reference=reference)
        .first()
    )


def _amount(payload: dict) -> int:
    amount = payload.get('amount') or {}
    return int(amount.get('value', 0))


def _handle_created(payload: dict) -> None:
    reference = payload.get('reference', '')
    with transaction.atomic():
        order = _get_locked_order(reference)
        if not order:
            logger.warning('vipps.webhook.unknown_reference', extra={'reference': reference, 'event': 'CREATED'})
            return
        # CREATED is informational. Only advance state if we're still PENDING.
        if order.payment_status == 'PENDING':
            old_status = order.payment_status
            order.payment_status = 'CREATED'
            order.vipps_psp_reference = payload.get('pspReference', order.vipps_psp_reference)
            order.last_vipps_sync_at = djtz.now()
            order.save(update_fields=[
                'payment_status', 'vipps_psp_reference', 'last_vipps_sync_at',
            ])
            record_payment_status_change(
                order, old_status=old_status, new_status='CREATED', source='webhook',
            )


def _handle_authorized(payload: dict) -> None:
    reference = payload.get('reference', '')
    authorized_value = _amount(payload)
    capture_eligible = False

    with transaction.atomic():
        order = _get_locked_order(reference)
        if not order:
            logger.warning('vipps.webhook.unknown_reference', extra={'reference': reference, 'event': 'AUTHORIZED'})
            return

        # If we've already moved past AUTHORIZED (e.g. CAPTURED webhook arrived
        # first), keep the more advanced state.
        if order.payment_status in ('CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED'):
            return

        old_status = order.payment_status
        if authorized_value:
            order.vipps_authorized_amount = authorized_value
        if not order.authorized_at:
            order.authorized_at = djtz.now()
        order.last_vipps_sync_at = djtz.now()
        order.payment_status = 'AUTHORIZED'
        order.save(update_fields=[
            'vipps_authorized_amount', 'authorized_at',
            'last_vipps_sync_at', 'payment_status',
        ])
        record_payment_status_change(
            order, old_status=old_status, new_status='AUTHORIZED', source='webhook',
        )
        capture_eligible = True
        order_to_capture = order

    if capture_eligible:
        try:
            capture_payment(order_to_capture)
        except VippsAPIError:
            # Already logged inside capture_payment. The reconciler will retry.
            logger.exception(
                'vipps.webhook.capture_failed_will_reconcile',
                extra={'reference': reference, 'order_id': order_to_capture.pk},
            )


def _handle_captured(payload: dict) -> None:
    reference = payload.get('reference', '')
    captured_value = _amount(payload)

    with transaction.atomic():
        order = _get_locked_order(reference)
        if not order:
            logger.warning('vipps.webhook.unknown_reference', extra={'reference': reference, 'event': 'CAPTURED'})
            return
        old_status = order.payment_status
        # Webhook arrived before AUTHORIZED was processed — accept the forward jump.
        if captured_value > order.vipps_captured_amount:
            order.vipps_captured_amount = captured_value
        if not order.captured_at:
            order.captured_at = djtz.now()
        if not order.authorized_at:
            order.authorized_at = djtz.now()
        if order.vipps_authorized_amount < captured_value:
            order.vipps_authorized_amount = captured_value
        if order.payment_status not in ('REFUNDED', 'PARTIALLY_REFUNDED'):
            order.payment_status = 'CAPTURED'
        order.last_vipps_sync_at = djtz.now()
        order.save(update_fields=[
            'vipps_captured_amount', 'vipps_authorized_amount',
            'captured_at', 'authorized_at', 'payment_status', 'last_vipps_sync_at',
        ])
        record_payment_status_change(
            order, old_status=old_status, new_status=order.payment_status, source='webhook',
        )


def _handle_refunded(payload: dict) -> None:
    """Defensive handler: refunds are deferred from this round, but if ops
    issues one via the Vipps merchant portal we still want our DB to track
    the cumulative refunded amount and flip the status accordingly.
    """
    reference = payload.get('reference', '')
    refund_value = _amount(payload)

    with transaction.atomic():
        order = _get_locked_order(reference)
        if not order:
            logger.warning('vipps.webhook.unknown_reference', extra={'reference': reference, 'event': 'REFUNDED'})
            return
        old_status = order.payment_status
        order.vipps_refunded_amount = max(order.vipps_refunded_amount + refund_value, refund_value)
        if order.vipps_captured_amount and order.vipps_refunded_amount >= order.vipps_captured_amount:
            order.payment_status = 'REFUNDED'
        else:
            order.payment_status = 'PARTIALLY_REFUNDED'
        order.last_vipps_sync_at = djtz.now()
        order.save(update_fields=[
            'vipps_refunded_amount', 'payment_status', 'last_vipps_sync_at',
        ])
        record_payment_status_change(
            order, old_status=old_status, new_status=order.payment_status, source='webhook',
        )


def _handle_cancelled(payload: dict) -> None:
    reference = payload.get('reference', '')
    cancelled_value = _amount(payload)
    with transaction.atomic():
        order = _get_locked_order(reference)
        if not order:
            logger.warning('vipps.webhook.unknown_reference', extra={'reference': reference, 'event': 'CANCELLED'})
            return
        old_status = order.payment_status
        order.vipps_cancelled_amount = max(order.vipps_cancelled_amount, cancelled_value)
        if order.payment_status not in ('CAPTURED', 'REFUNDED', 'PARTIALLY_REFUNDED'):
            order.payment_status = 'CANCELLED'
        order.last_vipps_sync_at = djtz.now()
        order.save(update_fields=['vipps_cancelled_amount', 'payment_status', 'last_vipps_sync_at'])
        record_payment_status_change(
            order, old_status=old_status, new_status=order.payment_status, source='webhook',
        )


def _terminal_handler(state: str):
    def _handler(payload: dict) -> None:
        reference = payload.get('reference', '')
        with transaction.atomic():
            order = _get_locked_order(reference)
            if not order:
                logger.warning(
                    'vipps.webhook.unknown_reference',
                    extra={'reference': reference, 'event': state},
                )
                return
            # Don't downgrade an already-captured order.
            if order.payment_status in ('CAPTURED', 'REFUNDED', 'PARTIALLY_REFUNDED'):
                return
            old_status = order.payment_status
            order.payment_status = state
            order.last_vipps_sync_at = djtz.now()
            order.save(update_fields=['payment_status', 'last_vipps_sync_at'])
            record_payment_status_change(
                order, old_status=old_status, new_status=state, source='webhook',
            )
    return _handler


_DISPATCH = {
    'CREATED': _handle_created,
    'AUTHORIZED': _handle_authorized,
    'CAPTURED': _handle_captured,
    'REFUNDED': _handle_refunded,
    'CANCELLED': _handle_cancelled,
    'ABORTED': _terminal_handler('ABORTED'),
    'EXPIRED': _terminal_handler('EXPIRED'),
    'TERMINATED': _terminal_handler('TERMINATED'),
}
