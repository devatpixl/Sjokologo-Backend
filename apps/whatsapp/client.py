"""Thin WAHA (WhatsApp HTTP API) client — outbound text only.

WAHA runs as a Docker container on this same host, bound to 127.0.0.1, so
these calls never leave the machine. The container holds a linked-device
session for the shop's WhatsApp number; see ``WAHA_SETUP.md`` in the Moengros
repo for how the container and the phone pairing work.

Nothing in here raises. This sits in the Vipps payment path, and a WhatsApp
outage must never turn into a failed order.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)


def is_configured() -> bool:
    """True only when the feature is switched on and fully configured.

    Deliberately defaults to off: deploying this code changes nothing until
    ``WHATSAPP_ENABLED`` is set in the environment.
    """
    return bool(
        getattr(settings, 'WHATSAPP_ENABLED', False)
        and getattr(settings, 'WAHA_BASE_URL', '')
        and getattr(settings, 'WAHA_API_KEY', '')
        and getattr(settings, 'WAHA_SESSION', '')
    )


def send_text(chat_id: str, text: str) -> bool:
    """Send one WhatsApp text message. Returns True on success, never raises."""
    if not is_configured():
        log.debug('WhatsApp send skipped — disabled or not configured')
        return False
    if not chat_id:
        log.warning('WhatsApp send skipped — no chat id configured')
        return False

    base = str(settings.WAHA_BASE_URL).rstrip('/')
    timeout = getattr(settings, 'WAHA_TIMEOUT_SECONDS', 5)
    try:
        resp = requests.post(
            f'{base}/api/sendText',
            headers={'X-Api-Key': settings.WAHA_API_KEY},
            json={
                'session': settings.WAHA_SESSION,
                'chatId': chat_id,
                'text': text,
            },
            timeout=timeout,
        )
    except Exception:
        log.exception('WhatsApp send to %s failed (network/timeout)', chat_id)
        return False

    if resp.status_code >= 300:
        # 463 here means WhatsApp is refusing to message a stranger — the
        # recipient has to message the shop number once first.
        log.error(
            'WhatsApp send to %s failed [%s]: %s',
            chat_id, resp.status_code, resp.text[:300],
        )
        return False

    log.info('WhatsApp sent to %s', chat_id)
    return True


def session_status() -> str | None:
    """Current WAHA session state, e.g. ``WORKING``. None if unreachable.

    Used by the healthcheck: WhatsApp kills a linked device if its phone stays
    offline for 14 days, and the only symptom is messages silently stopping.
    """
    if not is_configured():
        return None
    base = str(settings.WAHA_BASE_URL).rstrip('/')
    try:
        resp = requests.get(
            f'{base}/api/sessions/{settings.WAHA_SESSION}',
            headers={'X-Api-Key': settings.WAHA_API_KEY},
            timeout=getattr(settings, 'WAHA_TIMEOUT_SECONDS', 5),
        )
        if resp.status_code >= 300:
            return None
        return resp.json().get('status')
    except Exception:
        log.exception('WhatsApp session status check failed')
        return None
