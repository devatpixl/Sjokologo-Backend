"""Profrakt (EDI) consignment creation.

Only one call lives here: POST /consignments, which registers the parcel with
the carrier and returns the tracking number and label PDF.

Deliberately NOT here: price estimation (POST /costs/v2). The storefront quotes
the price at checkout; this module is used later, when ops actually ships, so
the carrier is not told about a parcel that may never exist. Creating a
consignment cannot be undone: the Profrakt API has no cancel or delete
endpoint, which is why the admin action asks for confirmation first.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Sender = Sjoko Loco's shop in Ås. Price zones are calculated from postcode
# 1430. Note Profrakt overrides the consignor on the printed label with
# whatever is registered to the Profrakt account itself.
SENDER = {
    'name': 'SJOKO LOCO AS',
    'address1': 'Moerveien 1',
    'address2': '',
    'postcode': '1430',
    'city': 'Ås',
    'country': 'NO',
    'email': 'post@sjokoloco.no',
    'mobile': '+4746935996',
}

METHOD_CONFIG = {
    'bring-pickup-point': ('bring2_parcel_pickup_point', 'PROFRAKT_TRANSPORT_AGREEMENT'),
    'postnord-locker': ('postnord_19_box', 'PROFRAKT_POSTNORD_AGREEMENT'),
}


class ProfraktError(Exception):
    """Any failure creating the consignment. Carries a human-readable reason."""


def _setting(name: str) -> str:
    value = getattr(settings, name, '') or ''
    if not value:
        raise ProfraktError(f'Profrakt er ikke konfigurert: {name} mangler.')
    return value


def _headers() -> dict[str, str]:
    return {
        'X-Profrakt-Key': _setting('PROFRAKT_KEY'),
        'X-Profrakt-Sender': _setting('PROFRAKT_SENDER'),
        'X-Profrakt-Autoprint': 'false',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _iso_country(value: str) -> str:
    """Mirror the storefront mapping exactly: "Norge"/"norway"/"NO" become NO,
    anything else is passed through untouched so Profrakt rejects it loudly
    rather than us silently shipping a foreign address as Norwegian."""
    raw = (value or '').strip()
    return 'NO' if raw.lower().startswith('no') else raw


def build_consignment_entry(order, items: list[dict]) -> dict:
    method = order.shipping_method or ''
    if method not in METHOD_CONFIG:
        raise ProfraktError(
            f'Fraktmetode «{method or "ingen"}» kan ikke sendes med Bring/PostNord.'
        )
    product, agreement_setting = METHOD_CONFIG[method]

    if not order.pickup_point_number:
        raise ProfraktError('Ordren mangler hentested — kan ikke lage etikett.')

    return {
        'transportAgreement': int(_setting(agreement_setting)),
        'product': product,
        'parts': {
            'consignor': SENDER,
            'consignee': {
                'name': f'{order.ship_first_name} {order.ship_last_name}'.strip(),
                'address1': order.ship_address or '',
                'address2': '',
                'postcode': order.ship_postal_code or '',
                'city': order.ship_city or '',
                'country': _iso_country(order.ship_country),
                'email': order.ship_email or '',
                'mobile': order.ship_phone or '',
            },
            'servicePartner': {
                'number': order.pickup_point_number,
                'name': order.pickup_point_name or '',
                'address1': order.pickup_point_address1 or '',
                'postcode': order.pickup_point_postcode or '',
                'city': order.pickup_point_city or '',
                'country': order.pickup_point_country or 'NO',
            },
        },
        'items': items,
        # Deliberately no reference field: the schema's optional key is
        # `references` (an object), not `reference`, and the storefront payload
        # proven in production sends neither. Not adding an untested field to
        # a call that cannot be undone.
    }


def create_consignment(order) -> dict:
    """Register the parcel and return {id, number, pdf, tracking_url}."""
    from .shipping_calc import order_to_shipping_items

    base = _setting('PROFRAKT_BASE').rstrip('/')
    body = {'consignments': [build_consignment_entry(order, order_to_shipping_items(order))]}

    try:
        response = requests.post(
            f'{base}/consignments',
            json=body,
            headers=_headers(),
            timeout=getattr(settings, 'PROFRAKT_HTTP_TIMEOUT', 20),
        )
    except requests.RequestException as exc:
        logger.exception('profrakt.consignment.network_error', extra={'order': order.order_number})
        raise ProfraktError(f'Fikk ikke kontakt med Profrakt: {exc}') from exc

    if response.status_code not in (200, 201):
        logger.error(
            'profrakt.consignment.api_error',
            extra={'order': order.order_number, 'status': response.status_code,
                   'body': response.text[:500]},
        )
        raise ProfraktError(
            f'Profrakt svarte {response.status_code}: {response.text[:200]}'
        )

    data = response.json() if response.content else {}
    consignment = data.get('consignment') or (data.get('consignments') or [{}])[0] or data
    consignment_id = consignment.get('id') or consignment.get('consignmentId')
    number = consignment.get('number') or consignment.get('consignmentNumber')
    if not consignment_id or not number:
        logger.error('profrakt.consignment.malformed',
                     extra={'order': order.order_number, 'body': str(data)[:500]})
        raise ProfraktError('Profrakt svarte uten sporingsnummer.')

    return {
        'id': str(consignment_id),
        'number': str(number),
        'pdf': consignment.get('consignmentPdf') or consignment.get('pdfUrl') or '',
        'tracking_url': consignment.get('trackingUrl')
                        or (consignment.get('tracking') or {}).get('url') or '',
    }
