"""Single HTTP client for Vipps MobilePay ePayment.

All outbound Vipps calls go through this module. Direct ``requests`` calls
to Vipps URLs from elsewhere in the codebase are forbidden.

The client:
  * Fetches and caches an OAuth access token via Django's cache, with a DB
    fallback (``VippsAccessToken``) so a cold-started process doesn't have to
    hit the access-token endpoint before its first call.
  * Attaches the standard headers Vipps requires on every API call.
  * Retries 5xx and connection errors with exponential backoff, reusing the
    same Idempotency-Key so Vipps deduplicates server-side.
  * Auto-refreshes the access token once on 401 and retries the original
    request with the new token.
  * Maps non-success responses to ``VippsAPIError`` (with ``retryable`` set
    appropriately).

Sensitive headers and payload keys are scrubbed before being passed to
``logger.info``; the access token is never logged.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from .exceptions import VippsAPIError, VippsAuthError
from .logging_utils import redact_headers
from .models import VippsAccessToken

logger = logging.getLogger('apps.payments_vipps')

ACCESS_TOKEN_CACHE_KEY = 'vipps:access_token'
ACCESS_TOKEN_REFRESH_LOCK_KEY = 'vipps:access_token_refresh_lock'

# Retryable response statuses for outbound API calls.
RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class VippsConfig:
    base_url: str
    client_id: str
    client_secret: str
    subscription_key: str
    merchant_serial_number: str
    system_name: str
    system_version: str
    system_plugin_name: str
    system_plugin_version: str
    http_timeout: float

    @classmethod
    def from_settings(cls) -> 'VippsConfig':
        return cls(
            base_url=settings.VIPPS_BASE_URL.rstrip('/'),
            client_id=settings.VIPPS_CLIENT_ID,
            client_secret=settings.VIPPS_CLIENT_SECRET,
            subscription_key=settings.VIPPS_SUBSCRIPTION_KEY,
            merchant_serial_number=settings.VIPPS_MERCHANT_SERIAL_NUMBER,
            system_name=settings.VIPPS_SYSTEM_NAME,
            system_version=settings.VIPPS_SYSTEM_VERSION,
            system_plugin_name=settings.VIPPS_SYSTEM_PLUGIN_NAME,
            system_plugin_version=settings.VIPPS_SYSTEM_PLUGIN_VERSION,
            http_timeout=float(getattr(settings, 'VIPPS_HTTP_TIMEOUT', 4)),
        )


@dataclass(frozen=True)
class CachedToken:
    token: str
    expires_at: datetime  # timezone-aware UTC


class VippsClient:
    """Synchronous HTTP client wrapping the subset of Vipps APIs we need."""

    def __init__(self, config: VippsConfig | None = None, session: requests.Session | None = None):
        self._config = config or VippsConfig.from_settings()
        self._session = session or requests.Session()

    # ── Access tokens ──────────────────────────────────────────────────

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid access token, fetching/refreshing it as needed.

        Strategy:
          1. Check Django cache (Redis or LocMem). If valid, return.
          2. Fall back to DB row. If valid, repopulate cache and return.
          3. Acquire a short cache lock and call POST /accesstoken/get.
        """
        if not force_refresh:
            cached = self._read_cached_token()
            if cached and cached.expires_at > _now() + timedelta(seconds=120):
                return cached.token

        return self._refresh_access_token()

    def _read_cached_token(self) -> CachedToken | None:
        cached = cache.get(ACCESS_TOKEN_CACHE_KEY)
        if cached and isinstance(cached, dict):
            try:
                return CachedToken(token=cached['token'], expires_at=cached['expires_at'])
            except KeyError:
                pass
        # DB fallback
        row = VippsAccessToken.objects.order_by('-fetched_at').first()
        if row and row.expires_at > _now() + timedelta(seconds=120):
            ct = CachedToken(token=row.token, expires_at=row.expires_at)
            cache.set(
                ACCESS_TOKEN_CACHE_KEY,
                {'token': ct.token, 'expires_at': ct.expires_at},
                timeout=int((ct.expires_at - _now()).total_seconds() - 120),
            )
            return ct
        return None

    def _refresh_access_token(self) -> str:
        # Try to take a cluster-wide refresh lock so concurrent processes don't stampede.
        got_lock = cache.add(ACCESS_TOKEN_REFRESH_LOCK_KEY, '1', timeout=10)
        if not got_lock:
            # Another process is refreshing; wait briefly and re-check the cache.
            for _ in range(20):
                time.sleep(0.25)
                cached = self._read_cached_token()
                if cached:
                    return cached.token
            # Fall through and refresh ourselves if the other process never wrote a value.
        try:
            url = f'{self._config.base_url}/accesstoken/get'
            headers = {
                'client_id': self._config.client_id,
                'client_secret': self._config.client_secret,
                'Ocp-Apim-Subscription-Key': self._config.subscription_key,
                'Merchant-Serial-Number': self._config.merchant_serial_number,
            }
            logger.info(
                'vipps.token.refresh',
                extra={'url': url, 'method': 'POST', 'headers': redact_headers(headers)},
            )
            resp = self._session.post(url, headers=headers, timeout=self._config.http_timeout)
            if resp.status_code != 200:
                raise VippsAuthError(
                    f'Failed to fetch access token: status={resp.status_code} body={resp.text[:500]}'
                )
            payload = resp.json()
            token = payload['access_token']
            expires_in = int(payload.get('expires_in', 3600))
            expires_at = _now() + timedelta(seconds=expires_in)

            cache.set(
                ACCESS_TOKEN_CACHE_KEY,
                {'token': token, 'expires_at': expires_at},
                timeout=max(expires_in - 120, 60),
            )
            with transaction.atomic():
                VippsAccessToken.objects.all().delete()
                VippsAccessToken.objects.create(token=token, expires_at=expires_at)
            return token
        finally:
            try:
                cache.delete(ACCESS_TOKEN_REFRESH_LOCK_KEY)
            except Exception:  # pragma: no cover — cache backends shouldn't error here
                pass

    # ── Common request scaffold ────────────────────────────────────────

    def _common_headers(self, *, idempotency_key: UUID | str | None = None) -> dict[str, str]:
        headers = {
            'Authorization': f'Bearer {self.get_access_token()}',
            'Ocp-Apim-Subscription-Key': self._config.subscription_key,
            'Merchant-Serial-Number': self._config.merchant_serial_number,
            'Vipps-System-Name': self._config.system_name,
            'Vipps-System-Version': self._config.system_version,
            'Vipps-System-Plugin-Name': self._config.system_plugin_name,
            'Vipps-System-Plugin-Version': self._config.system_plugin_version,
            'Content-Type': 'application/json',
        }
        if idempotency_key is not None:
            headers['Idempotency-Key'] = str(idempotency_key)
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        idempotency_key: UUID | str | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        url = f'{self._config.base_url}{path}'
        backoff = 1.0
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            headers = self._common_headers(idempotency_key=idempotency_key)
            try:
                resp = self._session.request(
                    method, url, headers=headers, json=json,
                    timeout=self._config.http_timeout,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                logger.warning(
                    'vipps.request.network_error',
                    extra={'url': url, 'method': method, 'attempt': attempt, 'error': str(exc)},
                )
                if attempt >= max_retries:
                    raise VippsAPIError(0, f'Network error: {exc}', retryable=True) from exc
                time.sleep(backoff)
                backoff *= 3
                continue

            request_id = resp.headers.get('Vipps-Request-Id') or resp.headers.get('x-request-id')
            logger.info(
                'vipps.request.completed',
                extra={
                    'url': url,
                    'method': method,
                    'status': resp.status_code,
                    'request_id': request_id,
                    'attempt': attempt,
                },
            )

            if resp.status_code == 401 and attempt == 0:
                # Token may have been invalidated; force-refresh and retry once.
                self.get_access_token(force_refresh=True)
                continue

            if 200 <= resp.status_code < 300:
                if resp.status_code == 204 or not resp.content:
                    return {}
                return resp.json()

            retryable = resp.status_code in RETRYABLE_STATUSES
            if retryable and attempt < max_retries:
                time.sleep(backoff)
                backoff *= 3
                continue

            raise VippsAPIError(
                resp.status_code,
                resp.text,
                request_id=request_id,
                retryable=retryable,
            )

        # If we exit the loop without returning, raise the last seen exception.
        raise VippsAPIError(0, f'Request failed after retries: {last_exc}', retryable=True)

    # ── ePayment endpoints ─────────────────────────────────────────────

    def create_payment(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        return_url: str,
        payment_description: str,
        idempotency_key: UUID,
        user_flow: str = 'WEB_REDIRECT',
    ) -> dict[str, Any]:
        body = {
            'amount': {'currency': currency, 'value': amount_minor},
            'paymentMethod': {'type': 'WALLET'},
            'reference': reference,
            'returnUrl': return_url,
            'userFlow': user_flow,
            'paymentDescription': payment_description,
        }
        return self._request(
            'POST', '/epayment/v1/payments',
            json=body, idempotency_key=idempotency_key,
        )

    def get_payment(self, reference: str) -> dict[str, Any]:
        return self._request('GET', f'/epayment/v1/payments/{reference}')

    def capture_payment(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        idempotency_key: UUID,
    ) -> dict[str, Any]:
        body = {'modificationAmount': {'currency': currency, 'value': amount_minor}}
        return self._request(
            'POST', f'/epayment/v1/payments/{reference}/capture',
            json=body, idempotency_key=idempotency_key,
        )

    def cancel_payment(
        self,
        *,
        reference: str,
        idempotency_key: UUID,
    ) -> dict[str, Any]:
        return self._request(
            'POST', f'/epayment/v1/payments/{reference}/cancel',
            json={}, idempotency_key=idempotency_key,
        )

    def force_approve(
        self,
        *,
        reference: str,
        phone_number: str,
        token: str,
    ) -> dict[str, Any]:
        """Test-environment-only: simulate the customer approving a payment.

        Vipps refuses this call in production; we double-check here so an
        operator running the dev command against prod credentials by accident
        gets a clear error instead of a confusing 4xx.
        """
        if 'apitest.vipps.no' not in self._config.base_url:
            raise VippsAPIError(
                0,
                f'force_approve refuses to call non-test base_url={self._config.base_url!r}',
                retryable=False,
            )
        body = {'customer': {'phoneNumber': phone_number}}
        if token:
            body['token'] = token
        return self._request(
            'POST', f'/epayment/v1/test/payments/{reference}/approve',
            json=body,
        )

    # ── Webhook registration endpoints ─────────────────────────────────

    def register_webhook(self, url: str, events: list[str]) -> dict[str, Any]:
        return self._request(
            'POST', '/webhooks/v1/webhooks',
            json={'url': url, 'events': events},
        )

    def list_webhooks(self) -> list[dict[str, Any]]:
        result = self._request('GET', '/webhooks/v1/webhooks')
        if isinstance(result, list):
            return result
        # Some APIs wrap the list; defend against both shapes.
        return result.get('webhooks', [])  # type: ignore[return-value]

    def delete_webhook(self, webhook_id: str) -> None:
        self._request('DELETE', f'/webhooks/v1/webhooks/{webhook_id}')


def _now() -> datetime:
    return datetime.now(timezone.utc)
