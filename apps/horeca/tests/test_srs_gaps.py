"""Requirements that were specified but not built the first time round.

Each test names the K-number it exists for, because each of these was found by
re-reading the SRS against the code rather than by anything failing.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone as djtz

from apps.horeca.availability import earliest_eligible_date, lead_days_for
from apps.horeca.models import HorecaOrder, HorecaProduct, Logo
from apps.horeca.tests.conftest import make_logo

pytestmark = pytest.mark.django_db


def _draft(api, product, address, date, *, logo=None, trays=1):
    line = {'product': product.slug, 'tray_count': trays}
    if logo is not None:
        line.update({'with_logo': True, 'logo': str(logo.id)})
    res = api.post(reverse('horeca-orders'), {
        'lines': [line], 'delivery_window': '08-12',
        'address': str(address.id), 'delivery_date': date.isoformat(),
    }, format='json')
    assert res.status_code == 201, res.data
    return HorecaOrder.objects.get(pk=res.data['id'])


# ── K-28: order now, production waits ───────────────────────────────────────

def test_can_order_against_a_logo_that_is_still_awaiting_approval(
    api, company, product, address, cfg,
):
    """"En bestilling kan legges inn i mellomtiden" — blocking this dead-ends
    every first-time customer, who has no approved logo yet by definition."""
    pending = make_logo(company, status=Logo.Status.PENDING, name='Ny logo')
    date = earliest_eligible_date(has_logo=True, cfg=cfg)
    order = _draft(api, product, address, date, logo=pending)

    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 200, res.data
    order.refresh_from_db()
    assert order.status == HorecaOrder.Status.SENDT


def test_a_rejected_logo_cannot_be_ordered_with(
    api, company, product, address, cfg,
):
    """Pending is fine; rejected is not — we have already said we cannot
    print it, so accepting the order would only fail later."""
    rejected = make_logo(company, status=Logo.Status.REJECTED, name='Uskarp')
    rejected.rejection_reason = 'For tynne streker.'
    rejected.save()

    date = earliest_eligible_date(has_logo=True, cfg=cfg)
    order = _draft(api, product, address, date, logo=rejected)
    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 400
    assert 'avvist' in str(res.data['lines']).lower()


def test_production_is_blocked_while_a_logo_is_unapproved(
    api, admin_api, company, product, address, cfg,
):
    """The gate K-28 actually asks for: nothing reaches the edible-sheet
    printer on artwork nobody has looked at."""
    pending = make_logo(company, status=Logo.Status.PENDING, name='Ny logo')
    date = earliest_eligible_date(has_logo=True, cfg=cfg)
    order = _draft(api, product, address, date, logo=pending)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()

    url = reverse('admin_horeca_order_detail', args=[order.order_number])
    res = admin_api.patch(url, {'status': HorecaOrder.Status.PRODUKSJON},
                          format='json')
    assert res.status_code == 400
    assert 'godkjent' in str(res.data['status']).lower()
    order.refresh_from_db()
    assert order.status != HorecaOrder.Status.PRODUKSJON

    # Approve it, and production opens.
    admin_api.patch(reverse('admin_horeca_logo_detail', args=[pending.id]),
                    {'status': Logo.Status.APPROVED}, format='json')
    assert admin_api.patch(url, {'status': HorecaOrder.Status.PRODUKSJON},
                           format='json').status_code == 200


def test_an_order_without_a_logo_enters_production_freely(
    api, admin_api, product, address, cfg,
):
    date = earliest_eligible_date(cfg=cfg)
    order = _draft(api, product, address, date)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()

    res = admin_api.patch(
        reverse('admin_horeca_order_detail', args=[order.order_number]),
        {'status': HorecaOrder.Status.PRODUKSJON}, format='json',
    )
    assert res.status_code == 200


# ── K-43: per-product lead time ─────────────────────────────────────────────

def test_a_product_can_carry_a_longer_lead_than_the_default(cfg):
    """"Et brett som krever håndlaging kan ha lengre frist enn et
    standardbrett." The field existed but nothing read it."""
    slow = HorecaProduct.objects.create(
        slug='handlaget', name='Håndlaget brett',
        wholesale_price=Decimal('2400.00'), lead_time_days=21,
    )
    assert lead_days_for(has_logo=False, cfg=cfg) == cfg.lead_time_days_plain
    assert lead_days_for(has_logo=False, products=[slow], cfg=cfg) == 21


def test_the_longest_lead_in_the_basket_wins(cfg, product):
    """They are delivered together, so the slowest tray sets the date."""
    slow = HorecaProduct.objects.create(
        slug='handlaget', name='Håndlaget brett',
        wholesale_price=Decimal('2400.00'), lead_time_days=21,
    )
    assert lead_days_for(has_logo=False, products=[product, slow], cfg=cfg) == 21


def test_ordering_a_slow_product_too_soon_is_refused(api, address, cfg):
    slow = HorecaProduct.objects.create(
        slug='handlaget', name='Håndlaget brett',
        wholesale_price=Decimal('2400.00'), lead_time_days=21,
    )
    # A date that is fine for a standard tray but far too soon for this one.
    ok_for_standard = earliest_eligible_date(cfg=cfg) + timedelta(days=1)
    order = _draft(api, slow, address, ok_for_standard)

    res = api.post(reverse('horeca-order-send', args=[order.pk]))
    assert res.status_code == 400
    assert '21' in str(res.data['delivery_date'])


def test_the_calendar_reflects_the_basket(api, cfg):
    """?products= must change which days are open, or the customer is told one
    thing by the calendar and another by the server."""
    HorecaProduct.objects.create(
        slug='handlaget', name='Håndlaget brett',
        wholesale_price=Decimal('2400.00'), lead_time_days=21,
    )
    today = djtz.localdate()
    params = {'from': today.isoformat(),
              'to': (today + timedelta(days=40)).isoformat()}

    plain = api.get(reverse('horeca-availability'), params).data
    slow = api.get(reverse('horeca-availability'),
                   {**params, 'products': 'handlaget'}).data

    assert slow['earliest_date'] > plain['earliest_date']


# ── K-35: a one-off address ─────────────────────────────────────────────────

def test_an_order_can_carry_a_one_off_address(api, product, cfg):
    """Caterers deliver somewhere new most weeks; forcing every one-night venue
    into the address book turns it into a junk drawer."""
    date = earliest_eligible_date(cfg=cfg)
    res = api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 2}],
        'delivery_window': '08-12',
        'delivery_date': date.isoformat(),
        'one_off_address': {
            'street': 'Festplassen 1', 'postal_code': '5014', 'city': 'Bergen',
            'contact_name': 'Ola', 'contact_phone': '99887766',
            'instructions': 'Ring ved ankomst',
        },
    }, format='json')
    assert res.status_code == 201, res.data

    order = HorecaOrder.objects.get(pk=res.data['id'])
    assert api.post(reverse('horeca-order-send', args=[order.pk])).status_code == 200

    order.refresh_from_db()
    assert order.delivery_city == 'Bergen'
    assert order.delivery_contact_phone == '99887766'
    assert order.delivery_address_source is None, (
        'a one-off venue must not be resurrected by "bestill på nytt"'
    )
    from apps.horeca.models import DeliveryAddress
    assert not DeliveryAddress.objects.filter(city='Bergen').exists(), (
        'K-35 — "uten å lagre den"'
    )


def test_a_one_off_address_still_needs_a_reachable_phone(api, product, cfg):
    res = api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 1}],
        'delivery_window': '08-12',
        'delivery_date': earliest_eligible_date(cfg=cfg).isoformat(),
        'one_off_address': {
            'street': 'Festplassen 1', 'postal_code': '5014', 'city': 'Bergen',
            'contact_phone': '12',
        },
    }, format='json')
    assert res.status_code == 400


def test_saved_and_one_off_address_together_is_refused(api, product, address, cfg):
    res = api.post(reverse('horeca-orders'), {
        'lines': [{'product': product.slug, 'tray_count': 1}],
        'delivery_window': '08-12',
        'delivery_date': earliest_eligible_date(cfg=cfg).isoformat(),
        'address': str(address.id),
        'one_off_address': {
            'street': 'X', 'postal_code': '5014', 'city': 'Bergen',
            'contact_phone': '99887766',
        },
    }, format='json')
    assert res.status_code == 400


# ── K-8: colleague invitations ──────────────────────────────────────────────

def test_bedriftsadmin_can_invite_a_colleague(api, company, member):
    from django.core import mail
    mail.outbox.clear()

    res = api.post(reverse('horeca-members'),
                   {'email': 'souschef@continental.test', 'name': 'Per'},
                   format='json')
    assert res.status_code == 201, res.data
    assert res.data['role'] == 'bestiller'

    msg = next(m for m in mail.outbox if m.to == ['souschef@continental.test'])
    assert 'opprett-passord' in msg.body, 'a new colleague needs a way in'
    assert company.name in msg.body


def test_a_plain_bestiller_cannot_invite(other_api, other_company, other_member):
    from apps.horeca.models import Membership
    Membership.objects.filter(user=other_member).update(
        role=Membership.Role.BESTILLER,
    )
    res = other_api.post(reverse('horeca-members'),
                         {'email': 'noen@grand.no'}, format='json')
    assert res.status_code == 403


def test_inviting_someone_who_already_has_access_is_refused(api, member):
    res = api.post(reverse('horeca-members'),
                   {'email': member.email}, format='json')
    assert res.status_code == 400
    assert 'allerede' in str(res.data['email']).lower()


def test_a_member_can_be_deactivated_but_not_yourself(api, company, member):
    from apps.horeca.models import Membership
    invited = api.post(reverse('horeca-members'),
                       {'email': 'souschef@continental.test'}, format='json').data

    res = api.patch(reverse('horeca-member-detail', args=[invited['id']]),
                    {'is_active': False}, format='json')
    assert res.status_code == 200
    assert res.data['is_active'] is False

    mine = Membership.objects.get(user=member)
    blocked = api.patch(reverse('horeca-member-detail', args=[mine.id]),
                        {'is_active': False}, format='json')
    assert blocked.status_code == 400, (
        'the last admin must not be able to lock the company out'
    )


# ── K-7: a 60-minute reset that does not touch the consumer link ────────────

def test_horeca_reset_link_expires_after_an_hour(member):
    from apps.users.password_setup import (
        build_horeca_password_link, resolve_horeca_password_token,
    )
    token = build_horeca_password_link(member).split('token=')[1]

    assert resolve_horeca_password_token(token, max_age=59 * 60) == member
    assert resolve_horeca_password_token(token, max_age=-1) is None


def test_setting_a_password_kills_the_link(member):
    from apps.users.password_setup import (
        build_horeca_password_link, resolve_horeca_password_token,
    )
    token = build_horeca_password_link(member).split('token=')[1]
    member.set_password('nytt-passord-123')
    member.save()
    assert resolve_horeca_password_token(token) is None, 'single use'


def test_the_two_token_families_cannot_be_swapped(member, settings):
    """A distinct salt, so a consumer link cannot be replayed on the business
    endpoint or the other way round."""
    from apps.users.password_setup import (
        build_horeca_password_link, resolve_horeca_password_token,
        build_password_link, resolve_password_token,
    )
    horeca_token = build_horeca_password_link(member).split('token=')[1]
    assert resolve_password_token('x', horeca_token) is None

    consumer = build_password_link(member)
    uid = consumer.split('uid=')[1].split('&')[0]
    consumer_token = consumer.split('token=')[1]
    assert resolve_horeca_password_token(consumer_token) is None
    assert resolve_password_token(uid, consumer_token) == member


def test_the_consumer_timeout_is_still_seven_days(settings):
    assert settings.PASSWORD_RESET_TIMEOUT == 60 * 60 * 24 * 7


def test_reset_endpoint_never_reveals_whether_an_address_exists(api, member):
    from django.core import mail
    known = api.post(reverse('horeca-password-reset'),
                     {'email': member.email}, format='json')
    mail.outbox.clear()
    unknown = api.post(reverse('horeca-password-reset'),
                       {'email': 'finnes-ikke@example.test'}, format='json')
    assert known.status_code == unknown.status_code == 200
    assert known.data == unknown.data
    assert mail.outbox == [], 'nothing sent for an unknown address'


# ── K-54 / K-55 / K-56 / K-52: the admin's day ──────────────────────────────

def _sent(api, product, address, cfg, *, trays=2, logo=None, date=None):
    day = date or earliest_eligible_date(has_logo=logo is not None, cfg=cfg)
    order = _draft(api, product, address, day, logo=logo, trays=trays)
    api.post(reverse('horeca-order-send', args=[order.pk]))
    order.refresh_from_db()
    return order


def test_packing_list_carries_what_the_driver_needs(
    api, admin_api, product, address, cfg,
):
    order = _sent(api, product, address, cfg)
    res = admin_api.get(reverse('admin_horeca_packing_list'),
                        {'order': order.order_number})
    assert res.status_code == 200
    row = res.data[0]
    assert row['contact_phone'] == '22820000', 'K-54 names the phone explicitly'
    assert 'Stortingsgata' in row['address']
    assert row['window']
    assert row['lines'][0]['allergens'] == ['melk', 'soya']


def test_logo_bundle_names_files_by_order_number(
    api, admin_api, company, product, address, cfg,
):
    import io, zipfile
    logo = make_logo(company, name='Hovedlogo')
    order = _sent(api, product, address, cfg, trays=3, logo=logo)

    res = admin_api.get(reverse('admin_horeca_day_logos'),
                        {'date': order.delivery_date.isoformat()})
    assert res.status_code == 200
    assert res['Content-Type'] == 'application/zip'

    blob = b''.join(res.streaming_content)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        names = archive.namelist()
        assert any(order.order_number in n for n in names), (
            'K-55 — "med ordrenummer i filnavnet"'
        )
        assert 'ordrer.txt' in names
        manifest = archive.read('ordrer.txt').decode()
        assert f'{order.order_number}x3' in manifest


def test_logo_bundle_404s_when_there_is_nothing_to_print(admin_api, cfg):
    res = admin_api.get(reverse('admin_horeca_day_logos'),
                        {'date': (djtz.localdate() + timedelta(days=90)).isoformat()})
    assert res.status_code == 404


def test_admin_can_move_a_delivery_and_it_lands_in_the_history(
    api, admin_api, product, address, cfg,
):
    from django.core import mail
    order = _sent(api, product, address, cfg)
    original = order.delivery_date
    later = original + timedelta(days=3)
    mail.outbox.clear()

    res = admin_api.patch(
        reverse('admin_horeca_order_detail', args=[order.order_number]),
        {'delivery_date': later.isoformat(), 'note': 'Kunden ringte og ba om det'},
        format='json',
    )
    assert res.status_code == 200, res.data

    order.refresh_from_db()
    assert order.delivery_date == later
    event = order.events.filter(note__icontains='flyttet').first()
    assert event is not None, 'K-56 — the change must be in the history'
    assert str(original) in event.note and str(later) in event.note
    assert len(mail.outbox) == 1, 'and the customer is told'


def test_admin_cannot_move_a_delivery_onto_a_full_day(
    api, admin_api, product, address, cfg,
):
    """An agreed change must not quietly overbook the kitchen."""
    busy = earliest_eligible_date(cfg=cfg)
    _sent(api, product, address, cfg, trays=cfg.max_trays_per_day, date=busy)
    later = busy + timedelta(days=1)
    order = _sent(api, product, address, cfg, trays=2, date=later)

    res = admin_api.patch(
        reverse('admin_horeca_order_detail', args=[order.order_number]),
        {'delivery_date': busy.isoformat()}, format='json',
    )
    assert res.status_code == 400
    order.refresh_from_db()
    assert order.delivery_date == later, 'nothing moved'


def test_admin_order_list_can_filter_by_product(
    api, admin_api, product, address, cfg,
):
    _sent(api, product, address, cfg)
    hit = admin_api.get(reverse('admin_horeca_order_list'),
                        {'product': product.slug})
    miss = admin_api.get(reverse('admin_horeca_order_list'),
                         {'product': 'finnes-ikke'})
    assert len(hit.data) == 1
    assert len(miss.data) == 0
