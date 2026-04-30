"""Single source of truth for converting between order totals and Vipps' minor units.

Vipps requires every monetary value as an integer in minor units (øre for NOK).
Our Order model uses ``Decimal`` for totals. Floats are never used.
"""
from decimal import Decimal, ROUND_HALF_UP


MINOR_UNITS_PER_MAJOR = 100  # NOK has 100 øre per krone; same for DKK / EUR / SEK / USD / GBP


def to_minor_units(value: Decimal) -> int:
    """Convert a Decimal amount in major units (e.g. 199.50 NOK) to integer øre.

    Raises ValueError if the value cannot be represented exactly in minor units
    (i.e. has more than two decimal places of precision).
    """
    if not isinstance(value, Decimal):
        raise TypeError(f'Expected Decimal, got {type(value).__name__}')
    quantized = value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if quantized != value:
        # Defensive: reject silent truncation. Order totals should always be 2dp.
        raise ValueError(f'Amount {value} has sub-øre precision; refusing to truncate')
    return int(quantized * MINOR_UNITS_PER_MAJOR)


def from_minor_units(minor: int) -> Decimal:
    """Convert integer minor units back to a 2-decimal-place Decimal."""
    return (Decimal(minor) / Decimal(MINOR_UNITS_PER_MAJOR)).quantize(Decimal('0.01'))


def order_amount_minor(order) -> int:
    """Return the order total in Vipps' minor-unit format."""
    return to_minor_units(order.total)
