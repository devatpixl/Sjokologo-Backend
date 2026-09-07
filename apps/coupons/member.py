"""The one discount the checkout applies on its own.

A signed-in customer gets the loyalty code without typing anything, so the
promise on the checkout page has to track reality: if the coupon is retired or
deactivated in the admin, this returns ``None`` and the storefront stops
advertising it rather than offering a discount that no longer exists.
"""

from django.conf import settings

from .models import Coupon


def get_active_member_coupon() -> Coupon | None:
    """The configured loyalty coupon, but only while it is redeemable.

    ``is_currently_valid`` is called without a subtotal on purpose: this answers
    "is the offer live at all", not "does this particular cart qualify". The
    cart-size rule is still enforced when the code is actually applied, both in
    the validate endpoint and again when the order is created.
    """
    code = (getattr(settings, 'LOYALTY_DISCOUNT_CODE', '') or '').strip().upper()
    if not code:
        return None
    coupon = Coupon.objects.filter(code=code).first()
    if coupon is None:
        return None
    ok, _ = coupon.is_currently_valid()
    return coupon if ok else None


def member_coupon_payload(coupon: Coupon) -> dict:
    """What the storefront needs to show and apply the discount."""
    return {
        'code': coupon.code,
        'kind': coupon.kind,
        'value': str(coupon.value),
        'min_subtotal': str(coupon.min_subtotal),
    }
