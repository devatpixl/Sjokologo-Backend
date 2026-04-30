"""Guard the test-only ``force_approve`` against accidental prod use."""
from __future__ import annotations

import pytest

from apps.payments_vipps.client import VippsClient, VippsConfig
from apps.payments_vipps.exceptions import VippsAPIError


def _config(base_url: str) -> VippsConfig:
    return VippsConfig(
        base_url=base_url,
        client_id='id',
        client_secret='secret',
        subscription_key='sub',
        merchant_serial_number='123',
        system_name='sjokoloko',
        system_version='1.0',
        system_plugin_name='sjokoloko-vipps',
        system_plugin_version='1.0',
        http_timeout=4.0,
    )


def test_force_approve_refuses_production_base_url():
    client = VippsClient(config=_config('https://api.vipps.no'))
    with pytest.raises(VippsAPIError) as excinfo:
        client.force_approve(reference='sl-1', phone_number='4748049667', token='tok')
    assert 'force_approve refuses' in str(excinfo.value)


def test_force_approve_refuses_lookalike_base_url():
    # Defence in depth: anything that doesn't contain 'apitest.vipps.no' is rejected.
    client = VippsClient(config=_config('https://api.vipps.com'))
    with pytest.raises(VippsAPIError):
        client.force_approve(reference='sl-1', phone_number='4748049667', token='tok')
