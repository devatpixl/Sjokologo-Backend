from decimal import Decimal

import pytest

from apps.payments_vipps.amounts import to_minor_units, from_minor_units


@pytest.mark.parametrize('major, minor', [
    (Decimal('0.01'), 1),
    (Decimal('1.00'), 100),
    (Decimal('1.99'), 199),
    (Decimal('60.00'), 6000),
    (Decimal('999.99'), 99999),
    (Decimal('9999.99'), 999999),
])
def test_round_trip(major: Decimal, minor: int):
    assert to_minor_units(major) == minor
    assert from_minor_units(minor) == major


def test_rejects_sub_ore_precision():
    with pytest.raises(ValueError):
        to_minor_units(Decimal('1.005'))


def test_rejects_non_decimal_input():
    with pytest.raises(TypeError):
        to_minor_units(1.99)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_minor_units(199)  # type: ignore[arg-type]
