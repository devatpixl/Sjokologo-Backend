"""POST /api/admin/horeca/companies/ — creating a company from the panel.

Must behave identically to the Django admin form (apps/horeca/admin.py), or a
customer created one way cannot log in the other way.
"""
import pytest
from django.core import mail
from django.urls import reverse

from apps.horeca.models import Company, Membership
from apps.users.models import CustomUser

pytestmark = pytest.mark.django_db

URL = '/api/admin/horeca/companies/'


def _body(**over):
    b = {'name': 'Hotell Bristol', 'org_number': '915933149',
         'contact_email': 'kjokken@bristol.test', 'contact_person_name': 'Ola'}
    b.update(over)
    return b


def test_it_creates_company_user_and_invitation(admin_api):
    mail.outbox.clear()
    res = admin_api.post(URL, _body(), format='json')
    assert res.status_code == 201, res.data

    company = Company.objects.get(org_number='915933149')
    user = CustomUser.objects.get(email='kjokken@bristol.test')
    m = Membership.objects.get(company=company, user=user)

    assert company.status == Company.Status.ACTIVE, 'we vetted it by typing it in'
    assert company.approved_at is not None
    assert m.role == Membership.Role.BEDRIFTSADMIN
    assert user.user_type == 'horeca'
    assert not user.has_usable_password(), 'they choose their own password'
    assert len(mail.outbox) == 1


def test_member_count_comes_back_so_the_table_does_not_flicker(admin_api):
    res = admin_api.post(URL, _body(), format='json')
    assert res.data['member_count'] == 1


def test_it_refuses_to_hijack_a_consumer_account(admin_api):
    CustomUser.objects.create_user(email='privat@example.com', password='x',
                                   user_type='registered')
    res = admin_api.post(URL, _body(contact_email='privat@example.com'), format='json')
    assert res.status_code == 400
    assert 'kundekonto' in str(res.data)
    assert not Company.objects.filter(org_number='915933149').exists(), (
        'a refused contact must not leave a half-made company behind'
    )


def test_a_duplicate_org_number_is_refused(admin_api, company):
    res = admin_api.post(URL, _body(org_number=company.org_number), format='json')
    assert res.status_code == 400
    assert 'allerede registrert' in str(res.data)


def test_org_number_must_be_nine_digits(admin_api):
    res = admin_api.post(URL, _body(org_number='123'), format='json')
    assert res.status_code == 400


def test_without_a_contact_it_just_makes_a_company(admin_api):
    mail.outbox.clear()
    res = admin_api.post(URL, _body(contact_email='', contact_person_name=''), format='json')
    assert res.status_code == 201
    assert Membership.objects.filter(company__org_number='915933149').count() == 0
    assert len(mail.outbox) == 0


def test_a_normal_user_cannot_create_companies(api):
    res = api.post(URL, _body(), format='json')
    assert res.status_code in (401, 403), 'IsAdminUser must hold'


def test_a_transposed_org_number_is_caught(admin_api):
    """915933149 is valid; 915933194 transposes the last pair. A digit count
    would let it through, and it would not collide with anything."""
    res = admin_api.post(URL, _body(org_number='915933194'), format='json')
    assert res.status_code == 400
    assert 'ser ikke riktig ut' in str(res.data)


def test_a_valid_unused_org_number_is_accepted(admin_api):
    res = admin_api.post(URL, _body(org_number='912 000 001'), format='json')
    assert res.status_code == 201, res.data
    assert res.data['org_number'] == '912000001', 'spaces normalised away'
