"""K-1 and K-62 — one company must never reach another's data.

The requirement most likely to be broken by a *future* edit rather than this
one, which is why the last test reads the source of views.py: it fails the
moment somebody writes the next endpoint with a bare `.objects` query.

Note every expectation here is **404, not 403**. A 403 confirms the row exists,
which is itself a leak — it tells a caller that SLB-00042 is real and belongs
to somebody else.
"""
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.urls import reverse
from django.utils import timezone as djtz

from apps.horeca.availability import first_available_date
from apps.horeca.models import DeliveryAddress, HorecaOrder
from apps.horeca.tests.conftest import make_logo

pytestmark = pytest.mark.django_db


def _order_for(client, product, address, cfg):
    res = client.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 1}],
        'delivery_window': '08-12',
        'address': str(address.id),
        'delivery_date': first_available_date(cfg=cfg).isoformat(),
    }, format='json')
    assert res.status_code == 201, res.data
    order = HorecaOrder.objects.get(pk=res.data['id'])
    client.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()
    return order


def test_cannot_read_another_companys_order(
    api, other_api, product, address, cfg,
):
    order = _order_for(api, product, address, cfg)
    res = other_api.get(reverse('horeca-order-detail', args=[order.order_number]))
    assert res.status_code == 404, 'a 403 would confirm the order exists'


def test_cannot_cancel_another_companys_order(
    api, other_api, product, address, cfg,
):
    order = _order_for(api, product, address, cfg)
    res = other_api.post(reverse('horeca-order-cancel', args=[order.order_number]))
    assert res.status_code == 404
    order.refresh_from_db()
    assert order.status != HorecaOrder.Status.AVBESTILT


def test_cannot_repeat_another_companys_order(
    api, other_api, product, address, cfg,
):
    order = _order_for(api, product, address, cfg)
    res = other_api.post(reverse('horeca-order-repeat', args=[order.order_number]))
    assert res.status_code == 404


def test_order_list_only_ever_shows_your_own_company(
    api, other_api, product, address, cfg, other_company,
):
    mine = _order_for(api, product, address, cfg)
    theirs_address = DeliveryAddress.objects.create(
        company=other_company, label='Kjøkken', contact_phone='22820001',
        street='Karl Johans gate 1', postal_code='0154', city='Oslo',
    )
    theirs = _order_for(other_api, product, theirs_address, cfg)

    numbers = {row['order_number'] for row in api.get(reverse('horeca-orders')).data}
    assert mine.order_number in numbers
    assert theirs.order_number not in numbers


def test_cannot_read_or_edit_another_companys_address(api, other_api, address):
    assert other_api.get(
        reverse('horeca-address-detail', args=[address.id])
    ).status_code == 404
    assert other_api.patch(
        reverse('horeca-address-detail', args=[address.id]),
        {'city': 'Bergen'}, format='json',
    ).status_code == 404
    address.refresh_from_db()
    assert address.city == 'Oslo'


def test_cannot_download_another_companys_logo(api, other_api, logo):
    assert other_api.get(
        reverse('horeca-logo-file', args=[logo.id])
    ).status_code == 404
    assert other_api.get(
        reverse('horeca-logo-signed-url', args=[logo.id])
    ).status_code == 404


def test_cannot_order_with_another_companys_logo(
    other_api, other_company, product, cfg, logo,
):
    """The check that stops one hotel printing another's brand on a tray."""
    theirs = DeliveryAddress.objects.create(
        company=other_company, label='Kjøkken', contact_phone='22820001',
        street='Karl Johans gate 1', postal_code='0154', city='Oslo',
    )
    res = other_api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 1,
                   'with_logo': True, 'logo': str(logo.id)}],
        'delivery_window': '08-12',
        'address': str(theirs.id),
        'delivery_date': first_available_date(has_logo=True, cfg=cfg).isoformat(),
    }, format='json')
    assert res.status_code == 404, 'the logo belongs to another company'


def test_cannot_deliver_to_another_companys_address(
    other_api, other_company, product, address, cfg,
):
    res = other_api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 1}],
        'delivery_window': '08-12',
        'address': str(address.id),   # belongs to `company`, not `other_company`
        'delivery_date': first_available_date(cfg=cfg).isoformat(),
    }, format='json')
    assert res.status_code == 404


def test_logo_list_is_scoped(api, other_api, logo, other_company):
    make_logo(other_company, name='Deres logo')
    mine = {row['name'] for row in api.get(reverse('horeca-logos')).data}
    assert mine == {logo.name}


# ── the structural guard ────────────────────────────────────────────────────

def test_views_never_read_these_models_unscoped():
    """Crude on purpose, and it fails at exactly the right moment.

    Every customer-facing READ must go through apps/horeca/scoping.py. A bare
    `HorecaOrder.objects.filter(...)` in a view is how the isolation proved
    above stops being true, and it would not fail any other test in this file —
    the new endpoint simply would not be covered.

    Writes are exempt: `.objects.create(company=...)` sets the tenant
    explicitly and cannot return somebody else's row.

    A genuinely unscoped read must carry `# unscoped-ok:` and a reason on the
    same line, which makes it a visible, reviewable act rather than an
    oversight.
    """
    source = Path(__file__).resolve().parent.parent / 'views.py'
    offenders = []
    models = ('HorecaOrder', 'Logo', 'DeliveryAddress')
    reads = ('filter', 'get', 'all', 'exclude', 'first', 'last')

    for lineno, line in enumerate(source.read_text().splitlines(), start=1):
        if '# unscoped-ok:' in line:
            continue
        for model in models:
            for method in reads:
                if f'{model}.objects.{method}(' in line:
                    offenders.append(f'{lineno}: {model}.objects.{method}')
            if f'get_object_or_404({model}' in line:
                offenders.append(f'{lineno}: get_object_or_404({model})')

    assert not offenders, (
        'views.py reads these models directly instead of via scoping.py. '
        'Use a scoping helper, or annotate with "# unscoped-ok: <reason>". '
        f'Found: {offenders}'
    )
