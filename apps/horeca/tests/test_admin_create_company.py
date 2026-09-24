"""Creating a company by hand from the Django admin.

This is how accounts are made at launch: public self-registration (K-5) stays
closed until Sjoko Loco can actually approve people, so every company is one we
type in ourselves. The flow has to produce a company, a first user who is a
bedriftsadmin, and a way for that person to get in — all three, or it is not
usable.
"""
import pytest
from django.contrib.admin.sites import AdminSite
from django.core import mail
from django.test import RequestFactory

from apps.horeca.admin import CompanyAdmin, CompanyAdminForm
from apps.horeca.models import Company, Membership
from apps.users.models import CustomUser

pytestmark = pytest.mark.django_db


def _create(admin_user, **extra):
    """Drive the real admin form + save_model, not the model directly."""
    data = {
        'name': 'Hotell Bristol', 'org_number': '915933149',
        'status': Company.Status.ACTIVE, 'rejection_reason': '',
        'phone': '', 'email': '', 'invoice_street': '', 'invoice_postal_code': '',
        'invoice_city': '', 'invoice_country': 'Norge',
        'contact_email': '', 'contact_person_name': '',
    }
    data.update(extra)
    form = CompanyAdminForm(data)
    assert form.is_valid(), form.errors
    request = RequestFactory().post('/django-admin/horeca/company/add/')
    request.user = admin_user
    # the messages framework needs somewhere to put its output
    request._messages = type('M', (), {'add': lambda *a, **k: None})()
    ma = CompanyAdmin(Company, AdminSite())
    obj = form.save(commit=False)
    ma.save_model(request, obj, form, change=False)
    return obj


@pytest.fixture
def staff(db):
    return CustomUser.objects.create_superuser(
        email='terje@sjokoloco.no', password='x', name='Terje',
    )


def test_creating_with_a_contact_makes_all_three_things(staff):
    mail.outbox.clear()
    company = _create(staff, contact_email='kjokken@bristol.test',
                      contact_person_name='Ola Nordmann')

    user = CustomUser.objects.get(email='kjokken@bristol.test')
    membership = Membership.objects.get(company=company, user=user)

    assert user.user_type == 'horeca'
    assert membership.role == Membership.Role.BEDRIFTSADMIN, (
        'the first user must be able to invite the rest of the kitchen (K-8)'
    )
    assert membership.is_active
    assert not user.has_usable_password(), (
        'we must never set a password for a customer — they choose their own'
    )
    assert len(mail.outbox) == 1
    assert 'bedrift/nytt-passord' in mail.outbox[0].body or \
           'opprett-passord' in mail.outbox[0].body, (
        'the invitation is useless without a way to set a password'
    )


def test_a_company_we_typed_in_ourselves_is_already_approved(staff):
    company = _create(staff, contact_email='ny@bristol.test')
    assert company.status == Company.Status.ACTIVE
    assert company.approved_at is not None
    assert company.approved_by == staff, (
        'we vetted it by typing it in; it should not queue for our own approval'
    )


def test_it_refuses_to_hijack_an_existing_consumer_account(staff):
    CustomUser.objects.create_user(
        email='privat@example.com', password='hunter2', user_type='registered',
    )
    form = CompanyAdminForm({
        'name': 'X', 'org_number': '915933149', 'status': Company.Status.ACTIVE,
        'rejection_reason': '', 'phone': '', 'email': '', 'invoice_street': '',
        'invoice_postal_code': '', 'invoice_city': '', 'invoice_country': 'Norge',
        'contact_email': 'privat@example.com', 'contact_person_name': '',
    })
    assert not form.is_valid()
    assert 'kundekonto' in str(form.errors['contact_email'])


def test_a_guest_checkout_shell_is_promoted_not_refused(staff):
    guest = CustomUser.objects.create(email='gjest@example.com', user_type='guest')
    guest.set_unusable_password(); guest.save()

    company = _create(staff, contact_email='gjest@example.com')
    guest.refresh_from_db()
    assert guest.user_type == 'horeca'
    assert Membership.objects.filter(company=company, user=guest).exists()


def test_leaving_the_contact_blank_just_makes_a_company(staff):
    mail.outbox.clear()
    company = _create(staff)
    assert Membership.objects.filter(company=company).count() == 0
    assert len(mail.outbox) == 0, 'nobody to write to'


def test_a_dead_mail_server_does_not_lose_the_company(staff, monkeypatch):
    """The company and its user must survive an SMTP outage — otherwise a
    flaky mail server silently eats work we already did."""
    import apps.horeca.admin as admin_mod
    monkeypatch.setattr(admin_mod, 'send_horeca_invite_email',
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('smtp down')))
    company = _create(staff, contact_email='ny@bristol.test')
    assert Company.objects.filter(pk=company.pk).exists()
    assert Membership.objects.filter(company=company).count() == 1
