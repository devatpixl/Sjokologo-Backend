"""Who may see and do what in the HORECA portal.

Two classes, and the gap between them is requirement K-6 exactly: an unapproved
company may log in and look around, but may not send an order.

    IsHorecaUser          -> browsing, own profile, addresses, logos
    IsApprovedHorecaUser  -> sending an order

`company_for_request` is the single place a company is derived from a user.
Every query in this app goes through it, and no view is permitted to take a
company id from the request body — that would be the whole tenant boundary
handed to the caller.
"""
from rest_framework.permissions import BasePermission

from .models import Company, Membership


def membership_for_request(request):
    """The caller's active membership, or None.

    Returns the first active membership. Multiple memberships per user are
    possible by design (the model is an FK pair, not a OneToOne), but nothing
    in the portal offers company switching yet, so picking the first is honest
    rather than clever — when switching arrives this is the one place to change.
    """
    # Memoised per request: the permission class asks, then the view asks
    # again, and on a list endpoint the serializer may ask once more. One query.
    if hasattr(request, '_horeca_membership'):
        return request._horeca_membership

    user = getattr(request, 'user', None)
    membership = None
    if user and user.is_authenticated:
        membership = (
            Membership.objects
            .select_related('company')
            .filter(user=user, is_active=True)
            .first()
        )
    request._horeca_membership = membership
    return membership


def company_for_request(request):
    """The caller's company, or None. The only sanctioned way to get one."""
    membership = membership_for_request(request)
    return membership.company if membership else None


class IsHorecaUser(BasePermission):
    """Signed in, with an active membership in some company."""

    message = 'Krever innlogging med en bedriftskonto.'

    def has_permission(self, request, view):
        return membership_for_request(request) is not None


class IsApprovedHorecaUser(BasePermission):
    """…and that company has been approved by Sjoko Loco (K-6)."""

    message = 'Bedriften må være godkjent før dere kan sende en bestilling.'

    def has_permission(self, request, view):
        company = company_for_request(request)
        return company is not None and company.status == Company.Status.ACTIVE


class IsBedriftsadmin(BasePermission):
    """Company administrator — may invite colleagues and edit addresses (K-8)."""

    message = 'Bare en bedriftsadmin kan gjøre dette.'

    def has_permission(self, request, view):
        membership = membership_for_request(request)
        return (
            membership is not None
            and membership.role == Membership.Role.BEDRIFTSADMIN
        )
