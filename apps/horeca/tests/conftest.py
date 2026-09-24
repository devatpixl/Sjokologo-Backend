"""Factories for the HORECA suite.

Deliberately plain functions rather than a factory library: the project has no
such dependency and these are small enough that adding one would be the larger
change.
"""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.horeca.models import (
    Company,
    DeliveryAddress,
    HorecaProduct,
    HorecaSettings,
    Logo,
    Membership,
)
from apps.users.models import CustomUser

# MOD-11-valid Norwegian organisasjonsnummer.
ORG_A = '915933149'
ORG_B = '923609016'


@pytest.fixture
def cfg(db):
    """The singleton settings row, with test-friendly numbers.

    Pinned rather than relying on the seed migration's defaults so a change to
    those defaults cannot silently alter what these tests assert.
    """
    settings_row = HorecaSettings.load()
    settings_row.max_trays_per_day = 40
    settings_row.lead_time_days_plain = 3
    settings_row.lead_time_days_logo = 7
    settings_row.lead_time_in_working_days = False  # simpler date arithmetic
    settings_row.delivery_weekdays = [0, 1, 2, 3, 4, 5, 6]  # no weekend blocking
    settings_row.contact_phone = '22 82 00 00'
    settings_row.save()
    return settings_row


@pytest.fixture
def company(db):
    return Company.objects.create(
        name='Hotell Continental', org_number=ORG_A,
        status=Company.Status.ACTIVE, email='post@continental.no',
    )


@pytest.fixture
def other_company(db):
    return Company.objects.create(
        name='Grand Hotel', org_number=ORG_B, status=Company.Status.ACTIVE,
    )


def make_member(company, email='kari@continental.no',
                role=Membership.Role.BEDRIFTSADMIN):
    user = CustomUser.objects.create(
        email=email, name='Kari Nordmann', user_type='horeca',
    )
    user.set_password('hemmelig123')
    user.save()
    Membership.objects.create(user=user, company=company, role=role)
    return user


@pytest.fixture
def member(company):
    return make_member(company)


@pytest.fixture
def other_member(other_company):
    return make_member(other_company, email='per@grand.no')


@pytest.fixture
def api(member):
    client = APIClient()
    client.force_authenticate(user=member)
    return client


@pytest.fixture
def other_api(other_member):
    client = APIClient()
    client.force_authenticate(user=other_member)
    return client


@pytest.fixture
def admin_api(db):
    admin = CustomUser.objects.create(
        email='terje@sjokoloco.no', name='Terje', is_admin=True, is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def product(db):
    return HorecaProduct.objects.create(
        slug='signature-brett', name='Signature brett',
        pieces_per_tray_plain=88, pieces_per_tray_logo=81,
        wholesale_price=Decimal('1200.00'), vat_rate=Decimal('15.00'),
        ingredients_text='Kakao, sukker, melk.',
        allergens=['melk', 'soya'],
    )


@pytest.fixture
def address(company):
    return DeliveryAddress.objects.create(
        company=company, label='Hovedkjøkken',
        contact_name='Kari', contact_phone='22820000',
        street='Stortingsgata 24', postal_code='0117', city='Oslo',
        is_default=True,
    )


def make_logo(company, status=Logo.Status.APPROVED, name='Hovedlogo'):
    from django.core.files.base import ContentFile
    logo = Logo(
        company=company, name=name,
        original_filename='logo.png', detected_format='png',
        kind=Logo.Kind.RASTER, byte_size=2048,
        checksum_sha256='0' * 64, width_px=1200, height_px=1200,
        status=status,
    )
    logo.file.save('logo.png', ContentFile(b'not-a-real-png'), save=False)
    logo.save()
    return logo


@pytest.fixture
def logo(company):
    return make_logo(company)
