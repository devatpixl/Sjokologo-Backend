"""Company-scoped queries. K-1 and K-62 live here.

The rule this module exists to enforce: **a view never touches
`HorecaOrder.objects` (or Logo, or DeliveryAddress) directly.** It asks for a
scoped queryset and works from that.

The sibling B2B project enforces isolation with three hand-written
`.filter(company=...)` lines, no shared helper and no tests. It is correct
today and one forgotten line from not being — which is exactly the failure this
module is shaped to prevent. A test asserts views.py contains no bare
`.objects` access for these models.

Note `get_company_order` raises **404, not 403**. A 403 confirms the order
exists, which is itself a leak: it tells a caller that order number SLB-00042
is real and belongs to somebody else.
"""
from django.shortcuts import get_object_or_404

from .models import DeliveryAddress, HorecaOrder, Logo


def company_orders(company):
    return HorecaOrder.objects.filter(company=company)


def company_addresses(company, *, include_archived=False):
    qs = DeliveryAddress.objects.filter(company=company)
    return qs if include_archived else qs.filter(is_archived=False)


def company_logos(company, *, include_archived=False):
    qs = Logo.objects.filter(company=company)
    return qs if include_archived else qs.filter(is_archived=False)


def get_company_order(company, order_number) -> HorecaOrder:
    return get_object_or_404(
        company_orders(company)
        .select_related('company')
        .prefetch_related('lines', 'events'),
        order_number=order_number,
    )


def get_company_draft(company, pk) -> HorecaOrder:
    return get_object_or_404(company_orders(company), pk=pk, is_draft=True)


def get_company_address(company, pk) -> DeliveryAddress:
    return get_object_or_404(company_addresses(company), pk=pk)


def get_company_logo(company, pk) -> Logo:
    return get_object_or_404(company_logos(company, include_archived=True), pk=pk)
