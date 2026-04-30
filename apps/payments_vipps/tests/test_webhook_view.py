"""End-to-end test of the webhook view: signature verification, idempotency
log, and dispatch into the state machine.

Outbound HTTP (capture call) is patched out — we only verify local state.
"""
import base64
import hashlib
import hmac
import json
from decimal import Decimal

import pytest
from django.test import Client

from apps.orders.models import Order
from apps.payments_vipps import handlers
from apps.payments_vipps.models import (
    VippsWebhookEvent,
    VippsWebhookRegistration,
)


pytestmark = pytest.mark.django_db


SECRET = 'test-webhook-secret'
WEBHOOK_PATH = '/api/webhooks/vipps/'


@pytest.fixture
def webhook_registration():
    return VippsWebhookRegistration.objects.create(
        webhook_id='hook-1',
        url='https://example.test/api/webhooks/vipps/',
        events=['epayments.payment.authorized.v1'],
        secret=SECRET,
        is_active=True,
    )


@pytest.fixture
def order():
    return Order.objects.create(
        subtotal=Decimal('60.00'),
        shipping=Decimal('0.00'),
        total=Decimal('60.00'),
        payment_method='vipps',
        payment_status='CREATED',
        vipps_reference='sl-00001-abcd1234',
        vipps_currency='NOK',
        ship_first_name='Test', ship_last_name='User',
        ship_email='t@example.com', ship_phone='+4799999999',
        ship_address='Storgata 1', ship_postal_code='0150',
        ship_city='Oslo', ship_country='Norge',
    )


def _signed_request(client: Client, body: dict, *, host: str = 'testserver',
                    date: str = 'Mon, 14 Aug 2023 12:48:46 GMT'):
    raw = json.dumps(body).encode('utf-8')
    content_hash = base64.b64encode(hashlib.sha256(raw).digest()).decode('ascii')
    signing_string = f'POST\n{WEBHOOK_PATH}\n{date};{host};{content_hash}'
    sig = base64.b64encode(
        hmac.new(SECRET.encode(), signing_string.encode(), hashlib.sha256).digest()
    ).decode('ascii')
    return client.post(
        WEBHOOK_PATH,
        data=raw,
        content_type='application/json',
        HTTP_X_MS_DATE=date,
        HTTP_X_MS_CONTENT_SHA256=content_hash,
        HTTP_HOST=host,
        HTTP_AUTHORIZATION=f'Signature={sig}',
    )


def test_unsigned_request_rejected(client, webhook_registration, order):
    res = client.post(WEBHOOK_PATH, data='{}', content_type='application/json')
    assert res.status_code == 401
    assert VippsWebhookEvent.objects.count() == 0


def test_signed_authorized_webhook_processes_once(client, webhook_registration, order, monkeypatch):
    captured = []
    def fake_capture(o, client=None):
        captured.append(o.pk)
        Order.objects.filter(pk=o.pk).update(
            payment_status='CAPTURED', vipps_captured_amount=6000,
        )
    monkeypatch.setattr(handlers, 'capture_payment', fake_capture)

    payload = {
        'msn': '123456',
        'reference': order.vipps_reference,
        'pspReference': 'psp-auth-1',
        'name': 'AUTHORIZED',
        'amount': {'currency': 'NOK', 'value': 6000},
        'timestamp': '2023-08-14T12:48:46.260Z',
        'success': True,
    }

    res = _signed_request(client, payload)
    assert res.status_code == 200

    order.refresh_from_db()
    assert order.payment_status == 'CAPTURED'
    assert order.vipps_authorized_amount == 6000
    assert VippsWebhookEvent.objects.count() == 1


def test_duplicate_delivery_is_a_noop(client, webhook_registration, order, monkeypatch):
    """Re-delivering the same pspReference must NOT trigger capture again."""
    capture_calls = []
    def fake_capture(o, client=None):
        capture_calls.append(o.pk)
        Order.objects.filter(pk=o.pk).update(
            payment_status='CAPTURED', vipps_captured_amount=6000,
        )
    monkeypatch.setattr(handlers, 'capture_payment', fake_capture)

    payload = {
        'msn': '123456',
        'reference': order.vipps_reference,
        'pspReference': 'psp-auth-2',
        'name': 'AUTHORIZED',
        'amount': {'currency': 'NOK', 'value': 6000},
        'timestamp': '2023-08-14T12:48:46.260Z',
        'success': True,
    }

    res1 = _signed_request(client, payload)
    res2 = _signed_request(client, payload)

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert VippsWebhookEvent.objects.count() == 1
    assert capture_calls == [order.pk]  # capture called exactly once


def test_unknown_reference_returns_200(client, webhook_registration):
    """An authentic webhook for an order we don't know must NOT cause Vipps
    to keep retrying — return 200, log a warning, and move on.
    """
    payload = {
        'msn': '123456',
        'reference': 'sl-99999-deadbeef',
        'pspReference': 'psp-orphan-1',
        'name': 'AUTHORIZED',
        'amount': {'currency': 'NOK', 'value': 6000},
        'timestamp': '2023-08-14T12:48:46.260Z',
        'success': True,
    }
    res = _signed_request(client, payload)
    assert res.status_code == 200


def test_signature_failure_does_not_create_event_row(client, webhook_registration, order):
    payload = {
        'msn': '123456',
        'reference': order.vipps_reference,
        'pspReference': 'psp-bad-1',
        'name': 'AUTHORIZED',
        'amount': {'currency': 'NOK', 'value': 6000},
        'timestamp': '2023-08-14T12:48:46.260Z',
        'success': True,
    }
    raw = json.dumps(payload).encode('utf-8')
    # Wrong signature on purpose.
    res = client.post(
        WEBHOOK_PATH,
        data=raw,
        content_type='application/json',
        HTTP_X_MS_DATE='Mon, 14 Aug 2023 12:48:46 GMT',
        HTTP_X_MS_CONTENT_SHA256=base64.b64encode(hashlib.sha256(raw).digest()).decode('ascii'),
        HTTP_HOST='testserver',
        HTTP_AUTHORIZATION='Signature=AAAA',
    )
    assert res.status_code == 401
    assert VippsWebhookEvent.objects.count() == 0
