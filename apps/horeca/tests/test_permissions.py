"""The guard tests.

This project sets DEFAULT_PERMISSION_CLASSES = AllowAny, so a view that forgets
`@permission_classes` is public and nothing complains. `apps/orders/views.py`
already ships full order PII that way. The first test below makes that mistake
impossible to repeat inside this app without a red build.

The rest cover K-1 (a company never sees another company's data) and K-6 (an
unapproved company may look but not order).
"""
import pytest
from django.urls import get_resolver, reverse
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from apps.horeca.models import Company, Membership
from apps.users.models import CustomUser

pytestmark = pytest.mark.django_db


# Endpoints that are meant to be reachable without a login, with the reason.
# Anything else resolving to AllowAny is a bug, not a decision.
INTENTIONALLY_PUBLIC = {
    'horeca-register': 'a business signs itself up before it has an account',
    'horeca-password-reset': (
        'you cannot authenticate to ask for a password reset. Answers 200 for '
        'every address so it cannot be used to enumerate customers.'
    ),
    'horeca-set-password': (
        'consumes a signed, 60-minute, single-use token (K-7) — the signature '
        'IS the authorisation, and the caller has no session yet by definition.'
    ),
    'horeca-logo-token-file': (
        'token-gated, not open: an <img> tag cannot carry an Authorization '
        'header, so the browser preview needs a signed URL. The signature IS '
        'the authorisation and it expires after 5 minutes.'
    ),
}


def _horeca_views():
    """Every view reachable under the horeca URL namespaces."""
    found = []
    for pattern in get_resolver().url_patterns:
        for sub in getattr(pattern, 'url_patterns', []):
            callback = getattr(sub, 'callback', None)
            name = getattr(sub, 'name', '') or ''
            if callback is None:
                continue
            module = getattr(callback, '__module__', '')
            if 'apps.horeca' in module or name.startswith('admin_horeca'):
                found.append((name, callback))
    return found


def test_no_horeca_view_is_accidentally_public():
    views = _horeca_views()
    assert views, 'no horeca views discovered — the URLconf walk is broken'

    offenders = []
    for name, callback in views:
        # @api_view attaches the generated APIView class as .cls
        cls = getattr(callback, 'cls', None)
        if cls is None:
            continue
        classes = list(getattr(cls, 'permission_classes', []))
        is_public = not classes or AllowAny in classes
        if is_public and name not in INTENTIONALLY_PUBLIC:
            offenders.append(name)

    assert not offenders, (
        'These HORECA views are public. Add @permission_classes, or add them to '
        f'INTENTIONALLY_PUBLIC with a reason: {offenders}'
    )


# ── fixtures ────────────────────────────────────────────────────────────────

def _company(name, org, status=Company.Status.ACTIVE):
    return Company.objects.create(name=name, org_number=org, status=status)


def _member(email, company, role=Membership.Role.BESTILLER):
    user = CustomUser.objects.create(email=email, name=email.split('@')[0],
                                     user_type='horeca')
    user.set_password('hemmelig123')
    user.save()
    Membership.objects.create(user=user, company=company, role=role)
    return user


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── K-6: approval gates ordering, not looking ───────────────────────────────

def test_pending_company_can_read_me_but_cannot_order():
    company = _company('Hotell Venter', '915933149', Company.Status.PENDING)
    user = _member('venter@hotell.no', company)

    res = _client_for(user).get(reverse('horeca-me'))
    assert res.status_code == 200, 'K-6: an unapproved company may still look'
    assert res.data['can_order'] is False
    assert res.data['company']['status'] == Company.Status.PENDING


def test_approved_company_may_order():
    company = _company('Hotell Klar', '923609016')
    user = _member('klar@hotell.no', company)

    res = _client_for(user).get(reverse('horeca-me'))
    assert res.status_code == 200
    assert res.data['can_order'] is True


def test_user_without_membership_is_refused():
    """A consumer account must not reach the portal at all."""
    user = CustomUser.objects.create(email='privat@kunde.no', name='Privat')
    res = _client_for(user).get(reverse('horeca-me'))
    assert res.status_code == 403


def test_anonymous_is_refused():
    assert APIClient().get(reverse('horeca-me')).status_code in (401, 403)


def test_deactivated_membership_loses_access_but_company_survives():
    """K-3 — deactivating a leaver must not delete the company's history."""
    company = _company('Hotell Turnover', '918643245')
    user = _member('sluttet@hotell.no', company)
    Membership.objects.filter(user=user).update(is_active=False)

    assert _client_for(user).get(reverse('horeca-me')).status_code == 403
    assert Company.objects.filter(pk=company.pk).exists()


# ── K-1: one company never sees another ─────────────────────────────────────

def test_me_only_ever_returns_the_callers_own_company():
    a = _company('Hotell A', '915933149')
    b = _company('Hotell B', '923609016')
    user_a = _member('a@hotell.no', a)
    _member('b@hotell.no', b)

    res = _client_for(user_a).get(reverse('horeca-me'))
    assert res.data['company']['org_number'] == a.org_number
    assert res.data['company']['org_number'] != b.org_number
