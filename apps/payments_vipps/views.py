"""HTTP views for the Vipps integration.

Three endpoints:
  * ``POST /api/checkout/vipps/create``   — start a Vipps payment for an order.
  * ``GET  /api/checkout/vipps/status``   — poll payment status from the return page.
  * ``POST /api/webhooks/vipps``          — receive signed Vipps webhooks.

The webhook view performs HMAC verification before any DB writes and inserts
the ``VippsWebhookEvent`` idempotency row in the same transaction as the
state transition, so duplicate deliveries are exact no-ops.
"""
from __future__ import annotations

import json
import logging
import secrets

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone as djtz
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from datetime import timedelta

from apps.orders.models import Order

from .amounts import order_amount_minor
from .capture import apply_aggregate_snapshot
from .client import VippsClient
from .exceptions import VippsAPIError, VippsSignatureError
from .handlers import handle_event
from .models import VippsWebhookEvent, VippsWebhookRegistration
from .signature import verify_webhook

logger = logging.getLogger('apps.payments_vipps')

REFERENCE_NONCE_LEN = 8  # bytes of random hex appended to the order id


def _build_reference(order: Order) -> str:
    prefix = getattr(settings, 'VIPPS_REFERENCE_PREFIX', 'sl').lower()
    nonce = secrets.token_hex(REFERENCE_NONCE_LEN // 2)  # 8 bytes hex = 16 chars; trim
    nonce = nonce[:REFERENCE_NONCE_LEN]
    return f'{prefix}-{order.pk:05d}-{nonce}'


def _user_owns_order(request: HttpRequest, order: Order) -> bool:
    user = getattr(request, 'user', None)
    if order.user_id is None:
        # Guest order: the storefront knows the order_number from the create-order
        # response. Treat possession of the order number as authorisation.
        return True
    if user and getattr(user, 'is_authenticated', False) and user.id == order.user_id:
        return True
    return False


# Note: @api_view (rather than a plain Django view) so SimpleJWT's
# DEFAULT_AUTHENTICATION_CLASSES fires and request.user is populated from the
# Bearer token. Plain Django views skip DRF auth → request.user would be
# AnonymousUser even with a valid JWT, breaking _user_owns_order.
@api_view(['POST'])
def create_payment_view(request) -> JsonResponse:
    body = request.data if isinstance(request.data, dict) else {}

    order_number = body.get('order_number') or body.get('order_id')
    if not order_number:
        return JsonResponse({'detail': 'order_number is required'}, status=400)

    try:
        order = Order.objects.get(order_number=order_number)
    except Order.DoesNotExist:
        return JsonResponse({'detail': 'Order not found'}, status=404)

    if not _user_owns_order(request, order):
        return JsonResponse({'detail': 'Forbidden'}, status=403)

    if order.total <= 0:
        return JsonResponse({'detail': 'Order total must be positive'}, status=400)

    # Reuse an existing live Vipps payment for the same order if there is one.
    if order.vipps_reference and order.payment_status in (
        'CREATED', 'AUTHORIZED', 'CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED',
    ):
        if order.vipps_redirect_url and order.payment_status == 'CREATED':
            return JsonResponse(
                {'redirectUrl': order.vipps_redirect_url, 'reference': order.vipps_reference},
                status=200,
            )
        # Already authorized/captured — there's nothing to redirect to.
        return JsonResponse(
            {'detail': 'Payment already in progress', 'reference': order.vipps_reference,
             'payment_status': order.payment_status},
            status=409,
        )

    if not order.vipps_reference:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order.pk)
            if not order.vipps_reference:
                order.vipps_reference = _build_reference(order)
                order.save(update_fields=['vipps_reference'])

    return_url = (
        getattr(settings, 'VIPPS_RETURN_URL_BASE', '').rstrip('/')
        + f'?reference={order.vipps_reference}'
    )

    client = VippsClient()
    import uuid
    idempotency_key = uuid.uuid4()

    try:
        result = client.create_payment(
            reference=order.vipps_reference,
            amount_minor=order_amount_minor(order),
            currency=order.vipps_currency or 'NOK',
            return_url=return_url,
            payment_description=f'Sjokoloko ordre {order.order_number}',
            idempotency_key=idempotency_key,
        )
    except VippsAPIError as exc:
        logger.exception(
            'vipps.create.api_error',
            extra={
                'order_id': order.pk,
                'reference': order.vipps_reference,
                'status_code': exc.status_code,
            },
        )
        return JsonResponse(
            {'detail': 'Failed to create Vipps payment'},
            status=502,
        )

    redirect_url = result.get('redirectUrl', '')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        order.vipps_redirect_url = redirect_url
        order.vipps_currency = order.vipps_currency or 'NOK'
        order.payment_status = 'CREATED'
        order.last_vipps_sync_at = djtz.now()
        order.save(update_fields=[
            'vipps_redirect_url', 'vipps_currency',
            'payment_status', 'last_vipps_sync_at',
        ])

    return JsonResponse(
        {'redirectUrl': redirect_url, 'reference': order.vipps_reference},
        status=201,
    )


# Possession of the long random vipps_reference (e.g. sl-00010-89ea39c0) is
# treated as the capability for reading payment status. The reference is only
# exposed to (a) Vipps via our CREATE call and (b) the buyer's browser via
# the redirect, and the response below is non-sensitive (status + amounts +
# currency, no PII, no items). Same model as a Posten tracking number.
#
# This avoids /kasse/retur 403'ing when:
#   - The buyer is a guest (no NextAuth session).
#   - The buyer's JWT expired between Fullfør and Vipps return.
#   - The buyer signed out in another tab during the Vipps redirect.

# How long the cached status is "fresh enough" before we re-poll Vipps.
# /kasse/retur polls every 1.5s; a 5s grace means at most one live Vipps
# call per ~3 polls per order — well under Vipps' 120/min/(reference,sub-key).
_LIVE_SYNC_GRACE = timedelta(seconds=5)
_TRANSIENT_STATES = ('PENDING', 'CREATED', 'AUTHORIZED', 'FAILED')


@api_view(['GET'])
def status_view(request) -> JsonResponse:
    reference = request.GET.get('reference', '')
    if not reference:
        return JsonResponse({'detail': 'reference is required'}, status=400)
    try:
        order = Order.objects.get(vipps_reference=reference)
    except Order.DoesNotExist:
        return JsonResponse({'detail': 'Not found'}, status=404)

    # Lazy reconciliation: if the order is in a transient state and we
    # haven't asked Vipps recently, do a live GET and converge state before
    # responding. This makes /kasse/retur reflect the truth in seconds even
    # when the ABORTED webhook is delayed or dropped (typical in dev with
    # ngrok URL rotation).
    if order.payment_status in _TRANSIENT_STATES:
        last_sync = order.last_vipps_sync_at
        stale = (last_sync is None) or (djtz.now() - last_sync > _LIVE_SYNC_GRACE)
        if stale:
            try:
                snapshot = VippsClient().get_payment(order.vipps_reference)
                order = apply_aggregate_snapshot(order, snapshot, source='reconciler')
            except VippsAPIError as exc:
                # Best-effort. Webhook + cron reconciler are still the
                # primary paths; the live sync is a UX optimisation only.
                logger.info(
                    'vipps.status.live_sync_failed',
                    extra={
                        'reference': reference,
                        'status_code': exc.status_code,
                    },
                )

    return JsonResponse({
        'reference': order.vipps_reference,
        'order_number': order.order_number,
        'payment_status': order.payment_status,
        'authorized_amount': order.vipps_authorized_amount,
        'captured_amount': order.vipps_captured_amount,
        'currency': order.vipps_currency,
    })


@csrf_exempt
@require_POST
def webhook_view(request: HttpRequest) -> HttpResponse:
    raw_body = request.body
    headers = {k.lower(): v for k, v in request.headers.items()}

    # Build path_and_query exactly as Vipps signed it.
    path_and_query = request.path
    qs = request.META.get('QUERY_STRING', '')
    if qs:
        path_and_query = f'{path_and_query}?{qs}'

    # Use the most recent active webhook secret. (We support exactly one active
    # registration per environment; ``vipps_register_webhooks`` enforces this.)
    registration = (
        VippsWebhookRegistration.objects
        .filter(is_active=True)
        .order_by('-created_at')
        .first()
    )
    if not registration:
        logger.error('vipps.webhook.no_registration')
        return HttpResponse(status=500)

    try:
        verify_webhook(
            raw_body=raw_body,
            method=request.method or 'POST',
            path_and_query=path_and_query,
            headers=headers,
            secret=registration.secret,
        )
    except VippsSignatureError as exc:
        logger.warning(
            'vipps.webhook.signature_failed',
            extra={'error': str(exc), 'remote_addr': request.META.get('REMOTE_ADDR')},
        )
        return HttpResponse(status=401)

    try:
        payload = json.loads(raw_body.decode('utf-8') or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning('vipps.webhook.bad_json')
        return HttpResponse(status=400)

    psp_reference = payload.get('pspReference', '')
    event_name = payload.get('name', '')
    reference = payload.get('reference', '')

    if not psp_reference:
        logger.warning('vipps.webhook.missing_psp_reference', extra={'payload_keys': list(payload.keys())})
        return HttpResponse(status=400)

    # Idempotency log + state transition in a single transaction.
    try:
        with transaction.atomic():
            try:
                event = VippsWebhookEvent.objects.create(
                    psp_reference=psp_reference,
                    event_name=event_name,
                    reference=reference,
                    payload=payload,
                )
            except IntegrityError:
                # Duplicate delivery — pspReference already seen. No-op, return 200.
                logger.info(
                    'vipps.webhook.duplicate_delivery',
                    extra={'psp_reference': psp_reference, 'event': event_name},
                )
                return HttpResponse(status=200)

            handle_event(event_name, payload)
            event.processed_at = djtz.now()
            event.save(update_fields=['processed_at'])
    except Exception as exc:
        logger.exception(
            'vipps.webhook.processing_error',
            extra={'psp_reference': psp_reference, 'event': event_name, 'reference': reference},
        )
        # Record the error on whatever event row exists (best-effort, outside the failed txn).
        try:
            VippsWebhookEvent.objects.filter(psp_reference=psp_reference).update(
                processing_error=str(exc)[:5000],
            )
        except Exception:  # pragma: no cover
            pass
        # Return 500 so Vipps retries. The reconciler is the second line of defence.
        return HttpResponse(status=500)

    return HttpResponse(status=200)
