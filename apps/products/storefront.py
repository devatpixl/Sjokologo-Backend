"""Tell the storefront to drop its cached product pages.

The Next.js shop caches product pages for 60s with stale-while-revalidate,
so after an edit the next request still serves the OLD page and only then
rebuilds. To whoever just clicked "Utsolgt" that looks like the toggle did
nothing — refresh once, product still there. This pings a small endpoint on
the storefront so the change is visible on the next refresh instead.

Best-effort by design: saving a product must never fail because the
storefront was slow or restarting. Worst case we fall back to the old
60-second behaviour.
"""
from __future__ import annotations

import logging

import requests
from django.conf import settings

log = logging.getLogger(__name__)


def revalidate_storefront(slug: str | None = None) -> bool:
    """Ask the storefront to re-render the shop pages. Never raises."""
    base = str(getattr(settings, 'REVALIDATE_URL', '') or '').rstrip('/')
    secret = getattr(settings, 'REVALIDATE_SECRET', '') or ''
    if not base or not secret:
        log.debug('Storefront revalidation skipped — not configured')
        return False

    try:
        resp = requests.post(
            f'{base}/api/revalidate',
            headers={'X-Revalidate-Secret': secret},
            json={'slug': slug} if slug else {},
            timeout=getattr(settings, 'REVALIDATE_TIMEOUT_SECONDS', 3),
        )
    except Exception:
        log.warning('Storefront revalidation failed (network/timeout)', exc_info=True)
        return False

    if resp.status_code >= 300:
        log.warning('Storefront revalidation failed [%s]: %s', resp.status_code, resp.text[:200])
        return False

    log.info('Storefront revalidated%s', f' for {slug}' if slug else '')
    return True
