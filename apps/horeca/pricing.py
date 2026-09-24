"""Price resolution.

One function, and it is the only place a HORECA price is ever decided.

Today it returns the list price, because the client's decision was a flat
wholesale price fully editable in the admin. The point of routing every call
site through here is that when Terje asks for agreed per-customer prices, this
function grows a lookup and **nothing else moves** — the serializers, the order
create path and the snapshot columns are already shaped for it.

`HorecaOrderLine.price_source` is what makes that a change rather than a
migration: historical lines already record how their price was decided, so new
sources ('company', 'group', 'manual') can appear with no backfill.
"""
from decimal import Decimal


def resolve_unit_price(product, company=None) -> tuple[Decimal, str]:
    """Price per tray, ex VAT, and how it was decided.

    `company` is unused today and deliberately kept in the signature — adding a
    parameter later would mean touching every call site, which is exactly the
    churn this indirection exists to avoid.
    """
    return product.wholesale_price, 'list'


def may_see_prices(company) -> bool:
    """K-6 + K-11 read together: a company that is not approved sees no prices.

    Belt and braces with the serializer's own check — this one is embarrassing
    to get wrong, so it is gated in two independent places.
    """
    return company is not None and company.can_order
