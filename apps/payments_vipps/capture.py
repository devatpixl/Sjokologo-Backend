"""Idempotent capture orchestration.

``capture_payment`` is called from two places:
  * The AUTHORIZED webhook handler — primary path.
  * The ``vipps_reconcile`` management command — fallback when the webhook
    handler crashed mid-call or when Vipps' AUTHORIZED webhook never reached us.

The function:
  1. Locks the order row (`SELECT ... FOR UPDATE`) and re-reads the state.
  2. Bails out if the order is already CAPTURED, CANCELLED, or in any other
     terminal state. Bails out if it isn't AUTHORIZED yet.
  3. Generates a persistent idempotency key on the order if absent. Vipps
     deduplicates by this key, so retries always return the same result.
  4. Calls ``VippsClient.capture_payment`` with the authorized amount.
  5. Updates the order state from the aggregate Vipps returns.

Capture amount source-of-truth: ``Order.vipps_authorized_amount`` (set from
the AUTHORIZED webhook payload), NOT ``Order.total``. This handles the rare
case where Vipps authorized a different amount than we requested.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from django.db import transaction
from django.utils import timezone as djtz

from apps.orders.models import Order

from .audit import record_payment_status_change
from .client import VippsClient
from .exceptions import VippsAPIError

logger = logging.getLogger('apps.payments_vipps')


def capture_payment(
    order: Order, *, client: VippsClient | None = None, source: str = 'webhook',
) -> Order:
    """Capture the authorized amount on the given order.

    Idempotent: re-running with no change in Vipps' state is a no-op.
    Raises ``VippsAPIError`` if Vipps refuses the capture for a non-retryable
    reason; the caller is responsible for marking the order ``FAILED`` and
    alerting.

    ``source`` is recorded on the resulting ``OrderAuditLog`` row — defaults
    to ``'webhook'`` (the AUTHORIZED handler is the primary caller); the
    reconciler passes ``'reconciler'``.
    """
    client = client or VippsClient()

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        if order.payment_status == 'CAPTURED':
            logger.info(
                'vipps.capture.already_captured',
                extra={'order_id': order.pk, 'reference': order.vipps_reference},
            )
            return order
        if order.payment_status not in ('AUTHORIZED',):
            logger.warning(
                'vipps.capture.unexpected_state',
                extra={
                    'order_id': order.pk,
                    'payment_status': order.payment_status,
                    'reference': order.vipps_reference,
                },
            )
            return order

        if not order.vipps_capture_idempotency_key:
            order.vipps_capture_idempotency_key = uuid.uuid4()
            order.save(update_fields=['vipps_capture_idempotency_key'])

        amount_minor = order.vipps_authorized_amount
        currency = order.vipps_currency or 'NOK'
        idem_key = order.vipps_capture_idempotency_key
        reference = order.vipps_reference

    # Outbound HTTP call happens OUTSIDE the transaction so we don't hold the
    # row lock across a multi-second network round-trip.
    try:
        result = client.capture_payment(
            reference=reference,
            amount_minor=amount_minor,
            currency=currency,
            idempotency_key=idem_key,
        )
    except VippsAPIError as exc:
        logger.exception(
            'vipps.capture.api_error',
            extra={
                'order_id': order.pk,
                'reference': reference,
                'status_code': exc.status_code,
                'retryable': exc.retryable,
                'request_id': exc.request_id,
            },
        )
        # 409 typically means the payment moved on (cancelled/captured already).
        # Trigger a reconcile-via-GET to converge instead of marking FAILED.
        if exc.status_code == 409:
            _reconcile_from_get(order, client=client, source=source)
            return order
        if not exc.retryable:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order.pk)
                old_status = order.payment_status
                order.payment_status = 'FAILED'
                order.last_vipps_sync_at = djtz.now()
                order.save(update_fields=['payment_status', 'last_vipps_sync_at'])
                record_payment_status_change(
                    order, old_status=old_status, new_status='FAILED',
                    source=source, note=f'Capture failed: {exc.status_code}',
                )
        raise

    # Persist the captured state from Vipps' aggregate response.
    aggregate = (result or {}).get('aggregate', {})
    captured = (aggregate.get('capturedAmount') or {}).get('value', amount_minor)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        old_status = order.payment_status
        order.vipps_captured_amount = captured
        order.captured_at = djtz.now()
        order.last_vipps_sync_at = djtz.now()
        order.payment_status = 'CAPTURED'
        order.save(update_fields=[
            'vipps_captured_amount',
            'captured_at',
            'last_vipps_sync_at',
            'payment_status',
        ])
        record_payment_status_change(
            order, old_status=old_status, new_status='CAPTURED', source=source,
        )

    logger.info(
        'vipps.capture.completed',
        extra={'order_id': order.pk, 'reference': reference, 'amount_minor': captured},
    )
    return order


def _reconcile_from_get(order: Order, *, client: VippsClient, source: str = 'webhook') -> None:
    """Fetch the authoritative aggregate from Vipps and converge the order.

    Used when capture returns 409 (state conflict) — we don't know if the
    payment is now CAPTURED, CANCELLED, or something else without asking.
    """
    try:
        snapshot = client.get_payment(order.vipps_reference)
    except VippsAPIError:
        logger.exception(
            'vipps.reconcile.get_failed',
            extra={'order_id': order.pk, 'reference': order.vipps_reference},
        )
        return

    apply_aggregate_snapshot(order, snapshot, source=source)


def apply_aggregate_snapshot(order: Order, snapshot: dict, *, source: str = 'reconciler') -> Order:
    """Update an Order row from a GET /payments/{reference} response.

    Used by the reconciler and by the 409-recovery path. Idempotent: runs
    inside its own transaction with row-locking and no-ops when state already
    matches.
    """
    aggregate = snapshot.get('aggregate', {}) or {}
    state = snapshot.get('state', '')
    authorized = (aggregate.get('authorizedAmount') or {}).get('value', 0)
    captured = (aggregate.get('capturedAmount') or {}).get('value', 0)
    refunded = (aggregate.get('refundedAmount') or {}).get('value', 0)
    cancelled = (aggregate.get('cancelledAmount') or {}).get('value', 0)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        old_status = order.payment_status

        # Vipps' top-level `state` only flips to CREATED/AUTHORIZED/ABORTED/
        # EXPIRED/TERMINATED — captures and refunds live in the aggregate.
        # Map to our payment_status, preferring the aggregate when relevant.
        new_status = order.payment_status
        if state in ('ABORTED', 'EXPIRED', 'TERMINATED'):
            new_status = state
        elif state == 'AUTHORIZED':
            if cancelled and cancelled >= authorized and captured == 0:
                new_status = 'CANCELLED'
            elif captured >= authorized and authorized > 0:
                new_status = 'CAPTURED'
                if refunded > 0:
                    new_status = 'REFUNDED' if refunded >= captured else 'PARTIALLY_REFUNDED'
            elif authorized > 0:
                new_status = 'AUTHORIZED'

        order.vipps_authorized_amount = authorized or order.vipps_authorized_amount
        order.vipps_captured_amount = max(captured, order.vipps_captured_amount)
        order.vipps_refunded_amount = max(refunded, order.vipps_refunded_amount)
        order.vipps_cancelled_amount = max(cancelled, order.vipps_cancelled_amount)
        order.last_vipps_sync_at = djtz.now()
        if new_status == 'CAPTURED' and not order.captured_at:
            order.captured_at = djtz.now()
        if authorized and not order.authorized_at:
            order.authorized_at = djtz.now()
        order.payment_status = new_status
        order.save()
        record_payment_status_change(
            order, old_status=old_status, new_status=new_status, source=source,
        )

    return order
