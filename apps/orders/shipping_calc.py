"""Parcel weight and box size for an order.

Ported from the storefront's lib/cart-shipping.ts so the backend can build the
same consignment the checkout quoted. The numbers come from the operator:
1 x 16-bite = 400 g, 2 x 16-bite = 750 g (not 800), because several boxes share
one outer parcel. Keep the two files in step.
"""

from __future__ import annotations

# PostNord parcel-locker chargeable weight cap.
MAX_LOCKER_GRAMS = 10_000

_FALLBACK_RULE = (200, 200)          # (first unit, each additional unit)
_CATEGORY_RULES = {
    'sjokoladebarer': (80, 80),
    'liten-sjokoladeboks': (200, 175),
    'stor-sjokoladeboks': (400, 350),
}
_SLUG_RULES = {
    # The gift pack already contains three boxes: fixed weight per line.
    'sjokoladeboks-gavepakke': (960, 960),
}
_CUSTOM_BOX_RULE = (350, 350)


def _rule_for(slug: str, category: str) -> tuple[int, int]:
    if slug in _SLUG_RULES:
        return _SLUG_RULES[slug]
    if slug.startswith('custom-'):
        return _CUSTOM_BOX_RULE
    return _CATEGORY_RULES.get(category, _FALLBACK_RULE)


def _line_grams(slug: str, category: str, qty: int) -> int:
    if qty <= 0:
        return 0
    first, additional = _rule_for(slug, category)
    return first + additional * (qty - 1)


def cart_total_grams(lines) -> int:
    """lines: iterable of (slug, category, quantity)."""
    return sum(_line_grams(s, c, q) for s, c, q in lines)


def pick_box(lines) -> dict[str, int]:
    """One outer parcel per order, sized by the largest applicable product."""
    if any(s == 'sjokoladeboks-gavepakke' for s, _, _ in lines):
        return {'length': 37, 'width': 37, 'height': 15}

    stor = sum(q for s, c, q in lines if c == 'stor-sjokoladeboks')
    if stor >= 3:
        return {'length': 37, 'width': 37, 'height': 15}
    if stor == 2:
        return {'length': 37, 'width': 37, 'height': 10}
    if stor == 1:
        return {'length': 37, 'width': 37, 'height': 5}
    if any(c == 'liten-sjokoladeboks' for _, c, _ in lines):
        return {'length': 22, 'width': 22, 'height': 5}
    if any(c == 'sjokoladebarer' for _, c, _ in lines):
        return {'length': 18, 'width': 6, 'height': 2}
    return {'length': 22, 'width': 22, 'height': 5}


def order_to_shipping_items(order) -> list[dict]:
    """The `items` array Profrakt expects for this order's single parcel."""
    lines = [
        (
            item.product.slug if item.product_id else '',
            item.product.category if item.product_id else '',
            item.quantity,
        )
        for item in order.items.all().select_related('product')
    ]
    grams = min(cart_total_grams(lines), MAX_LOCKER_GRAMS)
    box = pick_box(lines)
    return [{
        'itemType': 'package',
        'description': 'Sjoko Loco bestilling',
        'weight': round(max(0.1, grams / 1000), 3),
        'length': box['length'],
        'width': box['width'],
        'height': box['height'],
        'amount': 1,
    }]
