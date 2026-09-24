"""The fields the admin panel's Varebok editor sends.

This exists because the editor shipped with `supports_logo`, which is not a
field on HorecaProduct — the real name is `logo_available`. DRF ignores unknown
keys silently, so the checkbox appeared to work, saved nothing, and the Logo
column rendered a dash for every product. Nothing failed loudly.

If the panel starts sending a new key, add it here; if this test fails, the
panel and the model have drifted apart.
"""
import pytest
from django.urls import reverse

from apps.horeca.models import HorecaProduct

pytestmark = pytest.mark.django_db

# Mirrors the body built in admin/app/(dashboard)/horeca/varebok/_editor.tsx
PANEL_SENDS = {
    'name': 'Signature brett',
    'slug': 'signature-brett-test',
    'wholesale_price': '1200.00',
    'pieces_per_tray_plain': 88,
    'pieces_per_tray_logo': 81,
    'description': 'Beskrivelse',
    'logo_available': True,
    'is_active': True,
    'lead_time_days': None,
}


def test_every_key_the_panel_sends_is_a_real_field():
    model_fields = {f.name for f in HorecaProduct._meta.get_fields()}
    unknown = set(PANEL_SENDS) - model_fields
    assert not unknown, (
        f'the Varebok editor sends {unknown}, which HorecaProduct does not '
        f'have — DRF will drop them silently'
    )


def test_creating_with_exactly_that_body_persists_every_value(admin_api):
    res = admin_api.post('/api/admin/horeca/products/', PANEL_SENDS, format='json')
    assert res.status_code == 201, res.data
    p = HorecaProduct.objects.get(slug='signature-brett-test')
    assert p.name == 'Signature brett'
    assert str(p.wholesale_price) == '1200.00'
    assert p.pieces_per_tray_plain == 88
    assert p.pieces_per_tray_logo == 81
    assert p.logo_available is True
    assert p.is_active is True
    assert p.lead_time_days is None


def test_turning_the_logo_option_off_actually_sticks(admin_api):
    """The bug that started this: the checkbox saved nothing."""
    body = {**PANEL_SENDS, 'logo_available': False}
    res = admin_api.post('/api/admin/horeca/products/', body, format='json')
    assert res.status_code == 201, res.data
    assert HorecaProduct.objects.get(slug='signature-brett-test').logo_available is False
