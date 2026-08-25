"""Tokenised password-creation / reset links.

New customers register with name, e-mail and phone only — no password on the
form. The account is created with an unusable password and the welcome e-mail
carries a signed link where the customer chooses their own password. The same
machinery backs "glemt passord", so both flows share one token format.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import CustomUser


def build_password_link(user, path: str = '/opprett-passord') -> str:
    """Absolute storefront URL a customer follows to set their password."""
    uid = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = default_token_generator.make_token(user)
    base = (settings.STOREFRONT_URL or '').rstrip('/')
    return f'{base}{path}?uid={uid}&token={token}'


def resolve_password_token(uid: str, token: str) -> CustomUser | None:
    """Return the user a (uid, token) pair points at, or None if it is
    invalid, expired, or already spent.

    The token embeds the current password hash, so it stops working the
    moment a password is set — a link cannot be replayed.
    """
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = CustomUser.objects.get(pk=pk)
    except (CustomUser.DoesNotExist, ValueError, TypeError, OverflowError):
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user
