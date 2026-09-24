"""The order flow: pricing, tray maths, capacity, lead time, and K-38.

These are the tests whose failure would be either a wrong invoice or a promise
the kitchen cannot keep.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone as djtz

from apps.horeca.availability import first_available_date
from apps.horeca.models import Company, HorecaOrder

pytestmark = pytest.mark.django_db


def _payload(product, address, *, date=None, trays=2, with_logo=False, logo=None):
    body = {
        'lines': [{
            'product': product.slug,
            'tray_count': trays,
            'with_logo': with_logo,
        }],
        'delivery_window': '08-12',
        'address': str(address.id),
    }
    if logo is not None:
        body['lines'][0]['logo'] = str(logo.id)
    if date is not None:
        body['delivery_date'] = date.isoformat()
    return body


def _draft(api, product, address, cfg, **kw):
    date = kw.pop('date', None) or first_available_date(cfg=cfg)
    res = api.post(reverse('horeca-orders'),
                   _payload(product, address, date=date, **kw), format='json')
    assert res.status_code == 201, res.data
    return HorecaOrder.objects.get(pk=res.data['id'])


# ── pricing and tray maths ──────────────────────────────────────────────────

def test_price_is_resolved_server_side_and_client_price_ignored(
    api, product, address, cfg,
):
    res = api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 2,
                   'unit_price_ex_vat': '1.00'}],  # a lie
        'delivery_window': '08-12',
        'address': str(address.id),
        'delivery_date': first_available_date(cfg=cfg).isoformat(),
    }, format='json')
    assert res.status_code == 201

    order = HorecaOrder.objects.get(pk=res.data['id'])
    line = order.lines.get()
    assert line.unit_price_ex_vat == Decimal('1200.00')
    assert line.price_source == 'list'
    assert order.subtotal_ex_vat == Decimal('2400.00')


def test_plain_tray_is_88_and_logo_tray_is_81(api, product, address, logo, cfg):
    plain = _draft(api, product, address, cfg, trays=1)
    assert plain.lines.get().piece_count == 88

    with_logo = _draft(api, product, address, cfg,
                       trays=1, with_logo=True, logo=logo)
    line = with_logo.lines.get()
    assert line.pieces_per_tray == 81, 'K-12: the logo sheet replaces seven'
    assert line.piece_count == 81
    assert line.logo_name == logo.name


def test_vat_and_totals(api, product, address, cfg):
    order = _draft(api, product, address, cfg, trays=3)
    assert order.subtotal_ex_vat == Decimal('3600.00')
    assert order.vat_amount == Decimal('540.00')       # 15%
    assert order.total_inc_vat == Decimal('4140.00')
    assert order.tray_count == 3


def test_large_orders_are_accepted(api, product, address, cfg):
    """The consumer shop caps a line at 50 units. That must NOT apply here —
    a hundred trays is a normal conference order."""
    order = _draft(api, product, address, cfg, trays=100)
    assert order.tray_count == 100


def test_declaration_is_snapshotted_onto_the_line(api, product, address, cfg):
    """K-15 — the label must reproduce what was true when the order was placed."""
    order = _draft(api, product, address, cfg)
    line = order.lines.get()
    assert line.allergens_snapshot == ['melk', 'soya']
    assert 'Kakao' in line.ingredients_snapshot

    product.allergens = ['melk', 'soya', 'nøtter']
    product.ingredients_text = 'Helt andre ingredienser.'
    product.save()

    line.refresh_from_db()
    assert line.allergens_snapshot == ['melk', 'soya'], 'history must not move'


# ── K-38: the address is a copy, not a pointer ──────────────────────────────

def test_editing_an_address_does_not_rewrite_a_sent_order(
    api, product, address, cfg, member,
):
    order = _draft(api, product, address, cfg)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()
    assert order.delivery_street == 'Stortingsgata 24'

    api.patch(reverse('horeca-address-detail', args=[address.id]),
              {'street': 'Helt ny gate 1'}, format='json')

    order.refresh_from_db()
    assert order.delivery_street == 'Stortingsgata 24', (
        'K-38 — an order already placed must not silently change address'
    )


def test_archived_address_keeps_the_order_resolvable(api, product, address, cfg):
    order = _draft(api, product, address, cfg)
    api.delete(reverse('horeca-address-detail', args=[address.id]))

    address.refresh_from_db()
    assert address.is_archived is True, 'archived, never deleted'
    order.refresh_from_db()
    assert order.delivery_street == 'Stortingsgata 24'


# ── lead time and capacity (K-41 … K-47) ────────────────────────────────────

def test_a_date_inside_the_lead_time_is_refused(api, product, address, cfg):
    tomorrow = djtz.localdate() + timedelta(days=1)
    order = _draft(api, product, address, cfg, date=tomorrow)
    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 400
    assert 'dager' in str(res.data['delivery_date'])


def test_logo_orders_need_the_longer_lead(api, product, address, logo, cfg):
    plain_ok = djtz.localdate() + timedelta(days=4)  # > 3, < 7
    order = _draft(api, product, address, cfg,
                   date=plain_ok, trays=1, with_logo=True, logo=logo)
    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 400, 'K-41 — 7 days when a logo is printed'


def test_a_full_day_is_refused_and_names_the_next_free_one(
    api, product, address, cfg,
):
    date = first_available_date(cfg=cfg)
    first = _draft(api, product, address, cfg, date=date, trays=40)
    assert api.post(reverse('horeca-order-send', args=[first.pk])).status_code == 200

    second = _draft(api, product, address, cfg, date=date, trays=1)
    res = api.post(reverse('horeca-order-send', args=[second.pk]))
    assert res.status_code == 400
    detail = str(res.data['delivery_date'])
    assert 'Fullt' in detail or 'igjen' in detail
    assert 'Første' in detail, 'K-44 — say which day actually works'


def test_cancelling_frees_the_capacity_it_held(api, product, address, cfg):
    date = first_available_date(cfg=cfg)
    order = _draft(api, product, address, cfg, date=date, trays=40)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()

    api.post(reverse('horeca-order-cancel', args=[order.order_number]),
             {'reason': 'Arrangementet ble avlyst'}, format='json')

    res = api.get(reverse('horeca-availability'), {
        'from': date.isoformat(), 'to': date.isoformat(),
    })
    assert res.data['days'][0]['available'] is True
    assert res.data['days'][0]['trays_remaining'] == 40


def test_blocked_days_always_explain_themselves(api, cfg):
    """K-44 is a requirement about words, and the easiest one to skip."""
    res = api.get(reverse('horeca-availability'), {
        'from': djtz.localdate().isoformat(),
        'to': (djtz.localdate() + timedelta(days=10)).isoformat(),
    })
    assert res.status_code == 200
    for day in res.data['days']:
        if not day['available']:
            assert day['reason'], f'{day["date"]} is blocked with no reason'
            assert day['message'], f'{day["date"]} has no message for the customer'


# ── K-6 enforced server-side ────────────────────────────────────────────────

def test_pending_company_cannot_send_even_with_a_valid_draft(
    api, product, address, cfg, company,
):
    order = _draft(api, product, address, cfg)
    company.status = Company.Status.PENDING
    company.save()

    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 403, 'a hidden button is not a permission check'


def test_pending_company_sees_no_prices(api, product, company):
    company.status = Company.Status.PENDING
    company.save()
    res = api.get(reverse('horeca-products'))
    assert res.data[0]['price_ex_vat'] is None


def test_approved_company_sees_prices(api, product):
    res = api.get(reverse('horeca-products'))
    assert res.data[0]['price_ex_vat'] == '1200.00'


# ── order numbers ───────────────────────────────────────────────────────────

def test_order_number_series_is_distinct_from_the_consumer_shop(
    api, product, address, cfg,
):
    order = _draft(api, product, address, cfg)
    assert order.order_number is None, 'a draft has no number yet'

    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()
    assert order.order_number.startswith('SLB-')
    assert not order.order_number.startswith('SL-0'), (
        'must not collide with the consumer SL- series'
    )


def test_order_numbers_are_unique(api, product, address, cfg):
    numbers = set()
    for _ in range(3):
        order = _draft(api, product, address, cfg, trays=1)
        api.post(reverse('horeca-order-send', args=[order.pk]))
        order.refresh_from_db()
        numbers.add(order.order_number)
    assert len(numbers) == 3


# ── K-21 repeat ─────────────────────────────────────────────────────────────

def test_repeat_copies_the_lines_but_re_resolves_the_price(
    api, product, address, cfg,
):
    order = _draft(api, product, address, cfg, trays=4)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()

    product.wholesale_price = Decimal('1500.00')
    product.save()

    res = api.post(reverse('horeca-order-repeat', args=[order.order_number]))
    assert res.status_code == 201
    repeat = HorecaOrder.objects.get(pk=res.data['id'])
    assert repeat.is_draft is True
    assert repeat.lines.get().tray_count == 4
    assert repeat.lines.get().unit_price_ex_vat == Decimal('1500.00'), (
        'a repeat must not quietly charge last year\'s price'
    )
    assert repeat.delivery_date is None, 'the customer picks a new date'


# ── K-45 cancel deadline ────────────────────────────────────────────────────

def test_cancelling_after_the_deadline_is_refused_with_a_phone_number(
    api, product, address, cfg,
):
    order = _draft(api, product, address, cfg)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()

    # Move delivery to tomorrow, inside the 2-day cancel deadline.
    HorecaOrder.objects.filter(pk=order.pk).update(
        delivery_date=djtz.localdate() + timedelta(days=1),
    )
    res = api.post(reverse('horeca-order-cancel', args=[order.order_number]))
    assert res.status_code == 400
    assert cfg.contact_phone in str(res.data['detail']), (
        'K-45 — tell them how to reach a human instead'
    )
