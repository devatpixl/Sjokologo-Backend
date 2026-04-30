"""State-machine tests for the Vipps webhook event handlers.

We don't make any outbound HTTP calls here — the AUTHORIZED handler's call to
``capture_payment`` is patched to just flip the status so the test stays focused
on the local state transitions.
"""
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.orders.models import Order

from apps.payments_vipps import handlers
from apps.payments_vipps.models import VippsWebhookEvent


pytestmark = pytest.mark.django_db


def _make_order(payment_status: str = 'CREATED', authorized: int = 0, captured: int = 0) -> Order:
    return Order.objects.create(
        subtotal=Decimal('60.00'),
        shipping=Decimal('0.00'),
        total=Decimal('60.00'),
        payment_method='vipps',
        payment_status=payment_status,
        vipps_reference='sl-00001-abcd1234',
        vipps_authorized_amount=authorized,
        vipps_captured_amount=captured,
        vipps_currency='NOK',
        ship_first_name='Test', ship_last_name='User',
        ship_email='t@example.com', ship_phone='+4799999999',
        ship_address='Storgata 1', ship_postal_code='0150',
        ship_city='Oslo', ship_country='Norge',
    )


def _payload(name: str, amount: int = 6000, reference: str = 'sl-00001-abcd1234') -> dict:
    return {
        'name': name,
        'reference': reference,
        'pspReference': f'psp-{name.lower()}',
        'amount': {'currency': 'NOK', 'value': amount},
        'success': True,
    }


def test_created_event_advances_pending_to_created():
    order = _make_order(payment_status='PENDING')
    handlers.handle_event('CREATED', _payload('CREATED'))
    order.refresh_from_db()
    assert order.payment_status == 'CREATED'


def test_authorized_event_triggers_capture(monkeypatch):
    """The AUTHORIZED handler kicks capture_payment after flipping state."""
    order = _make_order(payment_status='CREATED')
    capture_calls: list[int] = []

    def fake_capture(o, client=None):
        capture_calls.append(o.pk)
        Order.objects.filter(pk=o.pk).update(payment_status='CAPTURED', vipps_captured_amount=6000)

    monkeypatch.setattr(handlers, 'capture_payment', fake_capture)

    handlers.handle_event('AUTHORIZED', _payload('AUTHORIZED'))
    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'
    assert order.vipps_authorized_amount == 6000
    assert order.vipps_captured_amount == 6000
    assert order.authorized_at is not None
    assert capture_calls == [order.pk]


def test_captured_event_advances_state():
    order = _make_order(payment_status='AUTHORIZED', authorized=6000)
    handlers.handle_event('CAPTURED', _payload('CAPTURED'))
    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'
    assert order.vipps_captured_amount == 6000
    assert order.captured_at is not None


def test_out_of_order_captured_before_authorized_converges():
    """If CAPTURED arrives before AUTHORIZED, accept the forward jump."""
    order = _make_order(payment_status='CREATED')
    handlers.handle_event('CAPTURED', _payload('CAPTURED', amount=6000))
    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'
    assert order.vipps_captured_amount == 6000
    # Late AUTHORIZED arrives: must NOT downgrade.
    with patch.object(handlers, 'capture_payment') as cap:
        handlers.handle_event('AUTHORIZED', _payload('AUTHORIZED', amount=6000))
        cap.assert_not_called()
    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'


def test_aborted_terminal_state():
    order = _make_order(payment_status='CREATED')
    handlers.handle_event('ABORTED', _payload('ABORTED', amount=0))
    order.refresh_from_db()
    assert order.payment_status == 'ABORTED'


def test_expired_terminal_state():
    order = _make_order(payment_status='CREATED')
    handlers.handle_event('EXPIRED', _payload('EXPIRED', amount=0))
    order.refresh_from_db()
    assert order.payment_status == 'EXPIRED'


def test_terminated_does_not_downgrade_captured_order():
    order = _make_order(payment_status='CAPTURED', authorized=6000, captured=6000)
    handlers.handle_event('TERMINATED', _payload('TERMINATED', amount=0))
    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'  # unchanged


def test_cancelled_event():
    order = _make_order(payment_status='AUTHORIZED', authorized=6000)
    handlers.handle_event('CANCELLED', _payload('CANCELLED', amount=6000))
    order.refresh_from_db()
    assert order.payment_status == 'CANCELLED'
    assert order.vipps_cancelled_amount == 6000


def test_refunded_event_marks_partially_refunded():
    order = _make_order(payment_status='CAPTURED', authorized=6000, captured=6000)
    handlers.handle_event('REFUNDED', _payload('REFUNDED', amount=2000))
    order.refresh_from_db()
    assert order.payment_status == 'PARTIALLY_REFUNDED'
    assert order.vipps_refunded_amount == 2000


def test_refunded_event_full_refund_marks_refunded():
    order = _make_order(payment_status='CAPTURED', authorized=6000, captured=6000)
    handlers.handle_event('REFUNDED', _payload('REFUNDED', amount=6000))
    order.refresh_from_db()
    assert order.payment_status == 'REFUNDED'
    assert order.vipps_refunded_amount == 6000


def test_unknown_reference_is_a_noop():
    """Webhook for a reference we don't have should not crash."""
    handlers.handle_event('AUTHORIZED', _payload('AUTHORIZED', reference='sl-99999-deadbeef'))
    # No assertion needed; the test passes if no exception was raised.
