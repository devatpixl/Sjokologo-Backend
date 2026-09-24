"""K-5 registration, and the approval decision that follows it (K-59)."""
import pytest
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from apps.horeca.models import Company, Membership
from apps.users.models import CustomUser

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def self_registration_on(settings):
    """K-5's public signup ships CLOSED (see settings.HORECA_SELF_REGISTRATION).
    These tests cover the feature itself, so they switch it on explicitly —
    which also means the default is pinned by exactly one test, below, rather
    than being an accident of whatever the environment happens to say."""
    settings.HORECA_SELF_REGISTRATION = True


def test_self_registration_is_closed_by_default(client, settings):
    """The guard that matters in production. If this ever starts failing, a
    public, unthrottled endpoint that creates accounts and sends mail from the
    shop's own SMTP has just been opened."""
    settings.HORECA_SELF_REGISTRATION = False
    res = client.post('/api/horeca/register/', {}, content_type='application/json')
    assert res.status_code == 403
    assert 'opprettes av Sjoko Loco' in res.json()['detail'], (
        'tell them how to get an account, do not just refuse'
    )

# Real MOD-11-valid Norwegian organisasjonsnummer shapes.
ORG_OK = '915933149'
ORG_OK_2 = '923609016'
ORG_BAD_CHECKSUM = '915933141'


def _payload(**over):
    body = {
        'company_name': 'Hotell Continental',
        'org_number': ORG_OK,
        'contact_name': 'Kari Nordmann',
        'email': 'kjokken@continental.no',
        'phone': '22820000',
        'invoice_street': 'Stortingsgata 24',
        'invoice_postal_code': '0117',
        'invoice_city': 'Oslo',
    }
    body.update(over)
    return body


def _register(**over):
    return APIClient().post(reverse('horeca-register'), _payload(**over), format='json')


# ── the happy path ──────────────────────────────────────────────────────────

def test_registration_creates_company_user_and_membership():
    res = _register()
    assert res.status_code == 201, res.data

    company = Company.objects.get(org_number=ORG_OK)
    assert company.status == Company.Status.PENDING, 'K-5: must wait for approval'
    assert res.data['company_status'] == Company.Status.PENDING

    user = CustomUser.objects.get(email='kjokken@continental.no')
    assert user.user_type == 'horeca'
    assert not user.has_usable_password(), 'password is set from the e-mailed link'

    membership = Membership.objects.get(user=user, company=company)
    assert membership.role == Membership.Role.BEDRIFTSADMIN, (
        'whoever registers must be an admin, or nobody could ever invite anyone'
    )


def test_registration_sends_a_welcome_mail_with_a_password_link(settings):
    # Pinned rather than inherited from the developer's .env: this list is empty
    # locally and populated in production, so a test that reads it is green or
    # red depending on whose machine it runs on.
    settings.ADMIN_NOTIFY_EMAILS = []
    _register()

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ['kjokken@continental.no']
    assert 'opprett-passord' in msg.body, 'a new account needs the set-password link'
    assert 'venter godkjenning' in msg.body.lower()


def test_ops_are_told_a_company_is_waiting(settings):
    """K-57 — but only when someone is actually configured to hear it."""
    settings.ADMIN_NOTIFY_EMAILS = ['post@sjokoloco.no']
    _register()

    ops = [m for m in mail.outbox if m.to == ['post@sjokoloco.no']]
    assert len(ops) == 1
    assert 'Ny HORECA-bedrift' in ops[0].subject
    assert 'Hotell Continental' in ops[0].body
    assert '915933149' in ops[0].body, 'org number is what admin looks up'


def test_no_ops_recipients_configured_is_not_an_error(settings):
    """The customer must still be registered and mailed."""
    settings.ADMIN_NOTIFY_EMAILS = []
    res = _register()
    assert res.status_code == 201
    assert len(mail.outbox) == 1


# ── org number ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', ['12345', '', 'abcdefghi'])
def test_malformed_org_numbers_are_refused(bad):
    """Shape is checked in both modes — it ends up on an invoice."""
    res = _register(org_number=bad)
    assert res.status_code == 400
    assert 'org_number' in res.data


def test_a_bad_checksum_passes_while_the_strict_flag_is_off():
    """Shipped default. Turned off at the client's request because it was
    rejecting the numbers they test with."""
    res = _register(org_number=ORG_BAD_CHECKSUM)
    assert res.status_code == 201


def test_a_bad_checksum_is_refused_when_strict(settings):
    settings.HORECA_STRICT_ORG_NUMBER = True
    res = _register(org_number=ORG_BAD_CHECKSUM)
    assert res.status_code == 400
    assert 'org_number' in res.data


def test_org_number_is_normalised_from_a_spaced_form():
    res = _register(org_number='915 933 149')
    assert res.status_code == 201
    assert Company.objects.filter(org_number=ORG_OK).exists()


def test_duplicate_company_points_at_the_invite_flow():
    _register()
    res = _register(email='annen@continental.no')
    assert res.status_code == 400
    assert 'invitere' in str(res.data['org_number']).lower(), (
        'K-8: the second person at a company arrives by invitation, so say so'
    )


# ── the decision that matters: one e-mail, one account ──────────────────────

def test_existing_consumer_account_is_reused_not_duplicated():
    existing = CustomUser.objects.create(
        email='kjokken@continental.no', name='Kari', user_type='registered',
    )
    existing.set_password('privat123')
    existing.save()

    res = _register()
    assert res.status_code == 201
    assert res.data['needs_password'] is False, 'they already have a password'

    assert CustomUser.objects.filter(email='kjokken@continental.no').count() == 1
    existing.refresh_from_db()
    assert existing.user_type == 'registered', (
        'they really are still a consumer customer; rewriting this would quietly '
        'remove them from the shop\'s own figures'
    )
    assert Membership.objects.filter(user=existing).exists()


# ── approval and rejection (K-59) ───────────────────────────────────────────

def _admin_client():
    admin = CustomUser.objects.create(email='terje@sjokoloco.no', name='Terje',
                                      is_admin=True, is_staff=True)
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


def test_approving_activates_the_company_and_mails_the_contact():
    _register()
    company = Company.objects.get(org_number=ORG_OK)
    mail.outbox.clear()

    res = _admin_client().patch(
        reverse('admin_horeca_company_detail', args=[company.pk]),
        {'status': Company.Status.ACTIVE}, format='json',
    )
    assert res.status_code == 200

    company.refresh_from_db()
    assert company.status == Company.Status.ACTIVE
    assert company.approved_at is not None
    assert company.approved_by is not None, 'who approved this is worth keeping'
    assert len(mail.outbox) == 1
    assert 'godkjent' in mail.outbox[0].subject.lower()


def test_rejecting_keeps_the_reason_and_sends_it_on():
    _register()
    company = Company.objects.get(org_number=ORG_OK)
    mail.outbox.clear()

    res = _admin_client().patch(
        reverse('admin_horeca_company_detail', args=[company.pk]),
        {'status': Company.Status.REJECTED,
         'rejection_reason': 'Fant ikke bedriften i Brønnøysund.'},
        format='json',
    )
    assert res.status_code == 200

    company.refresh_from_db()
    assert company.status == Company.Status.REJECTED
    assert 'Brønnøysund' in company.rejection_reason
    assert 'Brønnøysund' in mail.outbox[0].body


def test_re_saving_the_same_status_does_not_mail_twice():
    _register()
    company = Company.objects.get(org_number=ORG_OK)
    client = _admin_client()
    url = reverse('admin_horeca_company_detail', args=[company.pk])

    client.patch(url, {'status': Company.Status.ACTIVE}, format='json')
    mail.outbox.clear()
    client.patch(url, {'status': Company.Status.ACTIVE}, format='json')
    assert mail.outbox == [], 'only a real transition is worth an e-mail'


def test_non_admin_cannot_approve_a_company():
    _register()
    company = Company.objects.get(org_number=ORG_OK)
    user = CustomUser.objects.get(email='kjokken@continental.no')

    client = APIClient()
    client.force_authenticate(user=user)
    res = client.patch(
        reverse('admin_horeca_company_detail', args=[company.pk]),
        {'status': Company.Status.ACTIVE}, format='json',
    )
    assert res.status_code == 403
    company.refresh_from_db()
    assert company.status == Company.Status.PENDING


def test_company_list_puts_pending_first():
    _register()
    _register(org_number=ORG_OK_2, company_name='Hotell B',
              email='b@hotell.no')
    b = Company.objects.get(org_number=ORG_OK_2)
    b.status = Company.Status.ACTIVE
    b.save()

    res = _admin_client().get(reverse('admin_horeca_company_list'))
    assert res.status_code == 200
    assert res.data[0]['status'] == Company.Status.PENDING
    assert res.data[0]['member_count'] == 1


def test_guest_checkout_account_still_gets_a_password_link():
    """A guest row has no usable password, so treating it as an existing
    account would hand someone a company they can never sign in to.

    apps/users/views.py:guest_checkout_view creates these with
    user_type='guest' and set_unusable_password().
    """
    guest = CustomUser.objects.create(
        email='kjokken@continental.no', name='', user_type='guest',
    )
    guest.set_unusable_password()
    guest.save()

    res = _register()
    assert res.status_code == 201
    assert res.data['needs_password'] is True, (
        'a guest shell cannot log in — it must receive the set-password link'
    )

    guest.refresh_from_db()
    assert guest.user_type == 'horeca', 'the shell is promoted, not duplicated'
    assert guest.name == 'Kari Nordmann', 'a nameless guest gets the contact name'
    assert CustomUser.objects.filter(email='kjokken@continental.no').count() == 1

    msg = next(m for m in mail.outbox if m.to == ['kjokken@continental.no'])
    assert 'opprett-passord' in msg.body
