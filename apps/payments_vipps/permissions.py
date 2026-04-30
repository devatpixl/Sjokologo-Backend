from rest_framework.permissions import BasePermission

from apps.orders.models import Order


class IsAuthenticatedOrderOwner(BasePermission):
    """Permission that allows the authenticated user to act on an order they own.

    Used by the create-payment view; the order is looked up from request.data.
    Guests can also start a Vipps payment on a guest order (where ``order.user``
    is null), but only if they pass the matching order_number — this matches the
    existing 'place order as guest' flow.
    """

    def has_permission(self, request, view) -> bool:
        return True  # Per-object check happens inside the view.
