"""The admin surface: production list, status flow, logo review, settings."""
from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone as djtz

from apps.horeca.availability import first_available_date
from apps.horeca.models import HorecaOrder, HorecaSettings, Logo

pytestmark = pytest.mark.django_db


def _sent_order(api, product, address, cfg, *, trays=2, logo=None, date=None):
    """`date` is explicit where a test needs two orders on the SAME day — a
    logo order has a longer lead time, so the default dates differ."""
    line = {'product': product.slug, 'tray_count': trays}
    if logo is not None:
        line.update({'with_logo': True, 'logo': str(logo.id)})
    when = date or first_available_date(has_logo=logo is not None, cfg=cfg)
    res = api.post(reverse('horeca-orders'), {
        'lines': [line],
        'delivery_window': '08-12',
        'address': str(address.id),
        'delivery_date': when.isoformat(),
    }, format='json')
    assert res.status_code == 201, res.data
    order = HorecaOrder.objects.get(pk=res.data['id'])
    assert api.post(reverse('horeca-order-send', args=[order.pk])).status_code == 200
    order.refresh_from_db()
    return order


# ── K-53: the screen the SRS says matters most ──────────────────────────────

def test_production_list_aggregates_across_orders_by_product(
    api, admin_api, product, address, cfg, logo,
):
    # Both on the logo-eligible date, so one production day holds both.
    day = first_available_date(has_logo=True, cfg=cfg)
    _sent_order(api, product, address, cfg, trays=3, date=day)
    _sent_order(api, product, address, cfg, trays=2, logo=logo, date=day)

    res = admin_api.get(reverse('admin_horeca_production'),
                        {'date': day.isoformat()})
    assert res.status_code == 200

    row = next(r for r in res.data['by_product'] if r['slug'] == product.slug)
    assert row['trays_plain'] == 3
    assert row['trays_logo'] == 2
    assert row['trays'] == 5
    # 3×88 plain + 2×81 with a logo — the number the kitchen actually needs.
    assert row['pieces'] == 3 * 88 + 2 * 81
    assert res.data['trays_booked'] == 5
    assert res.data['trays_remaining'] == cfg.max_trays_per_day - 5


def test_production_list_groups_logo_jobs_for_the_print_shop(
    api, admin_api, product, address, cfg, logo,
):
    order = _sent_order(api, product, address, cfg, trays=4, logo=logo)
    res = admin_api.get(reverse('admin_horeca_production'),
                        {'date': order.delivery_date.isoformat()})

    job = res.data['logo_jobs'][0]
    assert job['logo_name'] == logo.name
    assert job['trays'] == 4, 'one edible sheet per tray'
    assert job['file_url'], 'the print shop needs to download it'


def test_cancelled_orders_leave_the_production_list(
    api, admin_api, product, address, cfg,
):
    order = _sent_order(api, product, address, cfg, trays=3)
    date = order.delivery_date.isoformat()
    assert admin_api.get(reverse('admin_horeca_production'),
                         {'date': date}).data['trays_booked'] == 3

    api.post(reverse('horeca-order-cancel', args=[order.order_number]))
    assert admin_api.get(reverse('admin_horeca_production'),
                         {'date': date}).data['trays_booked'] == 0


# ── status flow and K-49 e-mails ────────────────────────────────────────────

def test_status_change_writes_history_and_mails_once(
    api, admin_api, product, address, cfg,
):
    order = _sent_order(api, product, address, cfg)
    mail.outbox.clear()
    url = reverse('admin_horeca_order_detail', args=[order.order_number])

    res = admin_api.patch(url, {'status': HorecaOrder.Status.BEKREFTET},
                          format='json')
    assert res.status_code == 200
    assert len(mail.outbox) == 1
    assert 'bekreftet' in mail.outbox[0].subject.lower()

    order.refresh_from_db()
    assert order.confirmed_at is not None
    assert order.events.filter(to_status=HorecaOrder.Status.BEKREFTET).exists()

    mail.outbox.clear()
    admin_api.patch(url, {'status': HorecaOrder.Status.BEKREFTET}, format='json')
    assert mail.outbox == [], 'only a real transition is worth an e-mail'


def test_internal_states_send_no_customer_email(
    api, admin_api, product, address, cfg,
):
    """K-49 — "I produksjon" is our business, not news for the customer."""
    order = _sent_order(api, product, address, cfg)
    mail.outbox.clear()
    admin_api.patch(reverse('admin_horeca_order_detail', args=[order.order_number]),
                    {'status': HorecaOrder.Status.PRODUKSJON}, format='json')
    assert mail.outbox == []


def test_admin_can_cancel_and_the_customer_is_told(
    api, admin_api, product, address, cfg,
):
    order = _sent_order(api, product, address, cfg)
    mail.outbox.clear()
    admin_api.patch(reverse('admin_horeca_order_detail', args=[order.order_number]),
                    {'status': HorecaOrder.Status.AVBESTILT,
                     'note': 'Kunden ringte'}, format='json')
    order.refresh_from_db()
    assert order.status == HorecaOrder.Status.AVBESTILT
    assert len(mail.outbox) == 1


def test_non_admin_cannot_reach_the_admin_surface(api, product, address, cfg):
    order = _sent_order(api, product, address, cfg)
    assert api.get(reverse('admin_horeca_order_list')).status_code == 403
    assert api.get(reverse('admin_horeca_production')).status_code == 403
    assert api.patch(
        reverse('admin_horeca_order_detail', args=[order.order_number]),
        {'status': HorecaOrder.Status.LEVERT}, format='json',
    ).status_code == 403


# ── K-29: a rejection must carry a reason ───────────────────────────────────

def test_rejecting_a_logo_without_a_reason_is_refused(admin_api, logo):
    res = admin_api.patch(reverse('admin_horeca_logo_detail', args=[logo.id]),
                          {'status': Logo.Status.REJECTED}, format='json')
    assert res.status_code == 400
    assert 'rejection_reason' in res.data
    logo.refresh_from_db()
    assert logo.status == Logo.Status.APPROVED, 'nothing changed'


def test_rejecting_a_logo_with_a_reason_tells_the_customer(
    api, admin_api, company, member,
):
    from apps.horeca.tests.conftest import make_logo
    pending = make_logo(company, status=Logo.Status.PENDING, name='Ny logo')
    pending.uploaded_by = member
    pending.save()
    mail.outbox.clear()

    res = admin_api.patch(
        reverse('admin_horeca_logo_detail', args=[pending.id]),
        {'status': Logo.Status.REJECTED,
         'rejection_reason': 'Strekene er for tynne for spiseark.'},
        format='json',
    )
    assert res.status_code == 200
    assert 'tynne' in mail.outbox[0].body


# ── K-41: settings, not constants ───────────────────────────────────────────

def test_admin_can_change_capacity_and_the_calendar_follows(
    api, admin_api, cfg,
):
    """The client's explicit requirement, demonstrated end to end and with no
    restart."""
    admin_api.patch(reverse('admin_horeca_settings'),
                    {'max_trays_per_day': 5}, format='json')

    date = first_available_date(cfg=HorecaSettings.load())
    res = api.get(reverse('horeca-availability'),
                  {'from': date.isoformat(), 'to': date.isoformat()})
    assert res.data['max_trays_per_day'] == 5
    assert res.data['days'][0]['trays_remaining'] == 5


def test_settings_response_shows_what_the_change_means(admin_api, cfg):
    """Closing the loop: Terje should see the effect without opening the shop."""
    res = admin_api.patch(reverse('admin_horeca_settings'),
                          {'lead_time_days_plain': 14}, format='json')
    assert res.status_code == 200
    assert res.data['first_available_plain'] >= djtz.localdate() + timedelta(days=14)


def test_a_blackout_date_blocks_the_day_and_says_why(api, admin_api, cfg):
    date = first_available_date(cfg=cfg)
    admin_api.post(reverse('admin_horeca_blackout_list'),
                   {'date': date.isoformat(), 'reason': 'Julestengt'},
                   format='json')

    res = api.get(reverse('horeca-availability'),
                  {'from': date.isoformat(), 'to': date.isoformat()})
    day = res.data['days'][0]
    assert day['available'] is False
    assert day['reason'] == 'blackout'
    assert day['message'] == 'Julestengt', (
        "K-44 — the admin's own words reach the customer"
    )


# ── K-58 export ─────────────────────────────────────────────────────────────

def test_csv_export_is_excel_friendly(api, admin_api, product, address, cfg):
    order = _sent_order(api, product, address, cfg)
    res = admin_api.get(reverse('admin_horeca_order_export'))
    assert res.status_code == 200

    body = res.content.decode('utf-8')
    assert body.startswith('﻿'), 'BOM, or Excel on Windows mangles æøå'
    assert ';' in body.splitlines()[0], 'semicolons, or a Norwegian locale '\
                                        'puts every row in one column'
    assert order.order_number in body
    assert 'attachment' in res['Content-Disposition']


def test_export_route_is_not_swallowed_by_the_order_number_pattern(admin_api):
    """`orders/export/` sits above `orders/<str:order_number>/` for a reason."""
    res = admin_api.get(reverse('admin_horeca_order_export'))
    assert res.status_code == 200
    assert res['Content-Type'].startswith('text/csv')
