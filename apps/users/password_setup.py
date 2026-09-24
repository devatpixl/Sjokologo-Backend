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


# ── HORECA: a 60-minute reset link (K-7) ────────────────────────────────────
#
# PASSWORD_RESET_TIMEOUT is a single global set to 7 days and is consumed by
# default_token_generator above, so one setting cannot serve two lifetimes.
# The business flow therefore uses a second mechanism — django.core.signing
# with an explicit per-call max_age — which is exactly the pattern this project
# already uses for the Vipps OIDC state cookie. Nothing global changes, and the
# consumer welcome link keeps working for the full seven days.

import hashlib

from django.core import signing

HORECA_RESET_MAX_AGE_SECONDS = 60 * 60
HORECA_RESET_SALT = 'horeca-password-reset'


def _password_fingerprint(user) -> str:
    """A hash OF the password hash.

    `signing.dumps` is signed but NOT encrypted — the payload is readable
    base64 — so the raw hash must never travel in the token. This gives the
    same single-use property the built-in generator has: setting a password
    changes the fingerprint and kills every outstanding link.
    """
    return hashlib.sha256((user.password or '').encode()).hexdigest()[:32]


def build_horeca_password_link(user, path: str = '/bedrift/nytt-passord') -> str:
    # Outside /horeca on purpose: that section's layout does its own auth
    # redirect, and a reset page behind a login is a locked door with the key
    # behind it.
    token = signing.dumps(
        {'uid': str(user.pk), 'pw': _password_fingerprint(user)},
        salt=HORECA_RESET_SALT,
    )
    base = (settings.STOREFRONT_URL or '').rstrip('/')
    return f'{base}{path}?token={token}'


def resolve_horeca_password_token(
    token: str, max_age: int = HORECA_RESET_MAX_AGE_SECONDS,
) -> CustomUser | None:
    """The user a token points at, or None if it is invalid, expired or spent.

    The distinct salt means a consumer token cannot be replayed here and vice
    versa — tested both directions.
    """
    try:
        data = signing.loads(token, salt=HORECA_RESET_SALT, max_age=max_age)
    except signing.BadSignature:  # also covers SignatureExpired
        return None
    user = CustomUser.objects.filter(pk=data.get('uid'), is_active=True).first()
    if user is None or _password_fingerprint(user) != data.get('pw'):
        return None
    return user
