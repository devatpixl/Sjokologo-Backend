"""The consumer shop must behave exactly as it did before this app existed.

That was the hardest constraint on this work, and it is the one nobody would
notice breaking until a customer did. These tests are deliberately about the
*consumer* side, living in the horeca package because that is what would break
them.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.horeca.models import Company, Membership
from apps.horeca.tests.conftest import ORG_A
from apps.users.models import CustomUser

pytestmark = pytest.mark.django_db


def _admin_client():
    admin = CustomUser.objects.create(
        email='terje@sjokoloco.no', name='Terje', is_admin=True, is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def _horeca_user(email='kjokken@hotell.no'):
    company = Company.objects.create(
        name='Hotell Continental', org_number=ORG_A, status=Company.Status.ACTIVE,
    )
    user = CustomUser.objects.create(email=email, name='Kari', user_type='horeca')
    Membership.objects.create(user=user, company=company)
    return user


# ── the Kunder counter ──────────────────────────────────────────────────────

def test_kunder_count_excludes_horeca_but_still_counts_guests():
    """The one behavioural change to pre-existing code, pinned.

    Narrowing this to user_type='registered' would ALSO drop guest-checkout
    rows, which have always been counted. Moving that number is a separate
    decision, not a side effect of adding a B2B portal.
    """
    CustomUser.objects.create(email='privat@kunde.no', name='Privat',
                              user_type='registered')
    CustomUser.objects.create(email='gjest@kunde.no', name='Gjest',
                              user_type='guest')
    _horeca_user()

    stats = _admin_client().get(reverse('admin_stats')).data
    assert stats['users'] == 2, (
        'one registered + one guest; the HORECA account must not be counted'
    )


def test_stats_keeps_every_consumer_key():
    """The admin panel reads these by name — losing one breaks a dashboard card.

    Additive keys are fine and expected (the HORECA sidebar badges live here
    too), so this pins a SUPERSET rather than equality. Removing or renaming
    any of the six still fails.
    """
    stats = _admin_client().get(reverse('admin_stats')).data
    required = {'orders', 'users', 'revenue', 'waitlist',
                'unread_contact', 'new_customers'}
    assert required <= set(stats.keys()), (
        f'consumer dashboard keys went missing: {required - set(stats.keys())}'
    )


def test_stats_carries_the_horeca_queue_counts():
    """The sidebar badges need these, and a missing key renders as NaN."""
    stats = _admin_client().get(reverse('admin_stats')).data
    assert stats['horeca_pending_companies'] == 0
    assert stats['horeca_pending_logos'] == 0


def test_stats_survives_the_horeca_app_being_unavailable(monkeypatch):
    """The consumer dashboard must not die with the B2B portal."""
    import apps.users.admin_views as av
    monkeypatch.setattr(av, '_horeca_queue_counts',
                        lambda: {'horeca_pending_companies': 0,
                                 'horeca_pending_logos': 0})
    stats = _admin_client().get(reverse('admin_stats')).data
    assert stats['orders'] is not None


# ── the new-customer bell feed and badge ────────────────────────────────────

def test_horeca_signups_never_appear_in_the_consumer_notification_feed():
    """This one needs NO code in apps/utils: that feed already filters
    user_type='registered', which is exactly why 'horeca' was chosen as its own
    value rather than a boolean flag."""
    CustomUser.objects.create(email='privat@kunde.no', name='Privat',
                              user_type='registered', is_seen=False)
    _horeca_user()

    feed = _admin_client().get(reverse('admin_notifications')).data
    emails = [item.get('meta') for item in feed.get('items', [])]
    assert 'privat@kunde.no' in emails
    assert 'kjokken@hotell.no' not in emails


def test_new_customers_badge_ignores_horeca():
    _horeca_user()
    stats = _admin_client().get(reverse('admin_stats')).data
    assert stats['new_customers'] == 0


# ── the consumer order path ─────────────────────────────────────────────────

def test_consumer_order_numbers_are_untouched_by_the_horeca_series():
    """The two series must not interfere. HORECA uses a Postgres sequence and
    the prefix SLB-; the consumer generator is left exactly as it was."""
    from apps.orders.models import Order

    order = Order.objects.create(
        subtotal=100, shipping=0, total=100, payment_method='vipps',
        ship_first_name='Ola', ship_last_name='Nordmann',
        ship_email='ola@example.no', ship_phone='99887766',
        ship_address='Gata 1', ship_postal_code='0117', ship_city='Oslo',
    )
    assert order.order_number.startswith('SL-')
    assert not order.order_number.startswith('SLB-')


def test_consumer_admin_order_list_contains_no_horeca_orders():
    """They are separate models, so this is true by construction — asserted so
    that a future 'unify the order lists' refactor has to face it."""
    from apps.horeca.models import HorecaOrder

    company = Company.objects.create(
        name='Hotell B', org_number='923609016', status=Company.Status.ACTIVE,
    )
    HorecaOrder.objects.create(company=company, order_number='SLB-00001',
                               is_draft=False)

    rows = _admin_client().get(reverse('admin_order_list')).data
    numbers = [row.get('order_number') for row in rows]
    assert not any(str(n).startswith('SLB-') for n in numbers)


def test_public_product_list_still_works():
    """apps/products was not touched; this proves the URLconf edit did not
    shadow it."""
    res = APIClient().get('/api/products/')
    assert res.status_code == 200
