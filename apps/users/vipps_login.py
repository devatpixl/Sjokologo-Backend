"""Vipps Login (OIDC) integration.

Three endpoints implement the backend-driven OIDC authorization-code flow:

  GET  /api/auth/vipps/start/      — kicks off the flow, redirects to Vipps
  GET  /api/auth/vipps/callback/   — receives the auth code, mints a handoff JWT
  POST /api/auth/vipps/exchange/   — storefront trades the handoff JWT for a
                                     normal {access, refresh, user} login payload

PKCE (S256) is used unconditionally. State + nonce + code_verifier are stored
in short-lived signed HttpOnly cookies so we don't need server-side session.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
import urllib.parse
from functools import lru_cache
from typing import Optional

import jwt
import requests
from authlib.jose import JsonWebKey, JsonWebToken
from django.conf import settings
from django.core import signing
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import CustomUser, VippsIdentity
from .serializers import AuthResponseSerializer

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────

ISSUER_URL = settings.VIPPS_LOGIN_ISSUER_URL.rstrip('/')
USERINFO_URL = settings.VIPPS_LOGIN_USERINFO_URL
REDIRECT_URI = settings.VIPPS_LOGIN_REDIRECT_URI
SCOPES = settings.VIPPS_LOGIN_SCOPES
CLIENT_ID = settings.VIPPS_CLIENT_ID
CLIENT_SECRET = settings.VIPPS_CLIENT_SECRET
STOREFRONT_FINISH_URL = settings.VIPPS_LOGIN_STOREFRONT_FINISH_URL
HANDOFF_SECRET = settings.VIPPS_LOGIN_HANDOFF_SECRET
HANDOFF_TTL_SECONDS = 60
COOKIE_NAME = 'vipps_login_state'
COOKIE_MAX_AGE = 600  # 10 minutes — covers user dawdling in the Vipps app


# ── OIDC discovery (cached) ────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _discovery() -> dict:
    """Fetch and cache the OIDC well-known config from Vipps.

    Cached for the lifetime of the process; JWKS is fetched separately per-
    call below since keys can rotate.
    """
    url = f'{ISSUER_URL}/.well-known/openid-configuration'
    res = requests.get(url, timeout=8)
    res.raise_for_status()
    return res.json()


def _jwks() -> dict:
    """Fetch Vipps' JWKS. Not cached — let authlib refresh as needed."""
    url = _discovery()['jwks_uri']
    res = requests.get(url, timeout=8)
    res.raise_for_status()
    return res.json()


# ── PKCE helpers ───────────────────────────────────────────────────────────

def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _new_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    return verifier, challenge


# ── Signed cookie for state/nonce/verifier ─────────────────────────────────

def _pack_state(state: str, nonce: str, verifier: str, next_path: str) -> str:
    return signing.dumps(
        {'state': state, 'nonce': nonce, 'verifier': verifier, 'next': next_path},
        salt='vipps-login',
    )


def _unpack_state(token: str) -> dict:
    return signing.loads(token, salt='vipps-login', max_age=COOKIE_MAX_AGE)


# ── Endpoints ──────────────────────────────────────────────────────────────

@require_GET
def vipps_start_view(request):
    """Begin the OIDC dance — redirect customer to Vipps authorize endpoint."""
    next_param = request.GET.get('next', '/konto')
    # Only allow safe site-relative paths (defends against open redirect)
    if not next_param.startswith('/') or next_param.startswith('//'):
        next_param = '/konto'

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = _new_pkce_pair()

    params = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
        'nonce': nonce,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    }
    authorize_url = f'{_discovery()["authorization_endpoint"]}?{urllib.parse.urlencode(params)}'

    response = HttpResponseRedirect(authorize_url)
    response.set_cookie(
        COOKIE_NAME,
        _pack_state(state, nonce, verifier, next_param),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=not settings.DEBUG,  # http allowed for local dev only
        samesite='Lax',
    )
    return response


def _handoff_error_redirect(reason: str, next_path: str = '/logg-inn') -> HttpResponseRedirect:
    qs = urllib.parse.urlencode({'error': reason, 'next': next_path})
    return HttpResponseRedirect(f'{STOREFRONT_FINISH_URL}?{qs}')


@require_GET
def vipps_callback_view(request):
    """Receive Vipps' auth code, exchange it, build a handoff JWT."""
    code = request.GET.get('code')
    state_from_vipps = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        log.info('Vipps login declined: %s', error)
        return _handoff_error_redirect(error or 'vipps_declined')

    if not code or not state_from_vipps:
        return _handoff_error_redirect('missing_code_or_state')

    cookie = request.COOKIES.get(COOKIE_NAME)
    if not cookie:
        return _handoff_error_redirect('missing_state_cookie')

    try:
        unpacked = _unpack_state(cookie)
    except signing.BadSignature:
        return _handoff_error_redirect('bad_state_cookie')

    if not secrets.compare_digest(unpacked['state'], state_from_vipps):
        log.warning('Vipps state mismatch — possible CSRF')
        return _handoff_error_redirect('state_mismatch')

    nonce_expected = unpacked['nonce']
    verifier = unpacked['verifier']
    next_path = unpacked.get('next') or '/konto'

    # 1) Exchange auth code for tokens (with PKCE verifier).
    #    Vipps' default token endpoint auth method is `client_secret_basic`
    #    (per their core-concepts docs), so we send client_id/secret in an
    #    HTTP Basic Authorization header rather than the POST body. If the
    #    merchant has switched the auth method to `client_secret_post` in
    #    the business portal, requests still accepts duplicate credentials,
    #    so this works for both configurations.
    token_url = _discovery()['token_endpoint']
    try:
        token_res = requests.post(
            token_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': REDIRECT_URI,
                'code_verifier': verifier,
            },
            auth=(CLIENT_ID, CLIENT_SECRET),
            headers={'Accept': 'application/json'},
            timeout=8,
        )
    except requests.RequestException as e:
        log.exception('Vipps token exchange failed: %s', e)
        return _handoff_error_redirect('token_exchange_failed', next_path)

    if not token_res.ok:
        log.warning('Vipps token endpoint returned %s: %s', token_res.status_code, token_res.text[:300])
        return _handoff_error_redirect('token_exchange_rejected', next_path)

    token_data = token_res.json()
    id_token = token_data.get('id_token')
    access_token = token_data.get('access_token')
    if not id_token or not access_token:
        return _handoff_error_redirect('missing_tokens', next_path)

    # 2) Verify ID token: signature against JWKS, iss, aud, exp, nonce.
    try:
        jwks = JsonWebKey.import_key_set(_jwks())
        claims = JsonWebToken(['RS256', 'ES256']).decode(
            id_token,
            key=jwks,
            claims_options={
                'iss': {'essential': True, 'values': [_discovery()['issuer']]},
                'aud': {'essential': True, 'values': [CLIENT_ID]},
                'exp': {'essential': True},
            },
        )
        claims.validate()
    except Exception as e:
        log.warning('ID token validation failed: %s', e)
        return _handoff_error_redirect('id_token_invalid', next_path)

    if claims.get('nonce') != nonce_expected:
        log.warning('Vipps nonce mismatch')
        return _handoff_error_redirect('nonce_mismatch', next_path)

    sub = claims.get('sub')
    if not sub:
        return _handoff_error_redirect('no_sub', next_path)

    # 3) Fetch userinfo (name, email, phone) — these aren't in the ID token.
    try:
        ui_res = requests.get(
            USERINFO_URL,
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=8,
        )
        ui_res.raise_for_status()
        userinfo = ui_res.json()
    except requests.RequestException as e:
        log.exception('Userinfo fetch failed: %s', e)
        return _handoff_error_redirect('userinfo_failed', next_path)

    # 4) Upsert CustomUser + VippsIdentity.
    user = _upsert_user_from_vipps(sub, userinfo)

    # 5) Mint short-lived handoff JWT for the storefront to exchange.
    handoff = jwt.encode(
        {
            'user_id': str(user.id),
            'sub': sub,
            'iat': int(time.time()),
            'exp': int(time.time()) + HANDOFF_TTL_SECONDS,
            'kind': 'vipps_handoff',
        },
        HANDOFF_SECRET,
        algorithm='HS256',
    )

    response = HttpResponseRedirect(
        f'{STOREFRONT_FINISH_URL}?{urllib.parse.urlencode({"token": handoff, "next": next_path})}'
    )
    # Clear the state cookie — single-use.
    response.delete_cookie(COOKIE_NAME)
    return response


def _upsert_user_from_vipps(sub: str, userinfo: dict) -> CustomUser:
    """Find or create a CustomUser linked to this Vipps sub.

    Strategy (L1 — auto-link):
      1. If a VippsIdentity with this sub exists → return that user.
      2. Else if userinfo.email matches an existing CustomUser → link, return.
      3. Else create a fresh CustomUser + VippsIdentity.

    Vipps emails are BankID-verified so auto-linking by email is acceptable
    for this product. Flip to a confirmation flow if that ever changes.
    """
    existing = VippsIdentity.objects.select_related('user').filter(sub=sub).first()
    if existing:
        existing.last_userinfo = userinfo
        existing.save(update_fields=['last_userinfo', 'updated_at'])
        return existing.user

    email = (userinfo.get('email') or '').strip().lower()
    email_verified = bool(userinfo.get('email_verified'))
    name = (userinfo.get('name') or '').strip()
    phone = (userinfo.get('phone_number') or '').strip()
    phone_verified = bool(userinfo.get('phone_number_verified'))

    user: Optional[CustomUser] = None
    # Only auto-link to an existing email/password account when Vipps marks
    # the email as verified. An unverified email could let someone with a
    # Vipps account claim someone else's Sjokoloko account.
    if email and email_verified:
        user = CustomUser.objects.filter(email__iexact=email).first()

    if user is None:
        # Create. Email is required by the model; if Vipps didn't return one
        # (scope not granted, edge case) generate a deterministic placeholder
        # using the sub. The user can edit it from /konto later.
        if not email:
            email = f'vipps-{sub[:12]}@sjokoloko.local'
        user = CustomUser.objects.create(
            email=email,
            name=name or 'Vipps-bruker',
            # Only store the phone if Vipps verified it. Otherwise leave it
            # blank — the user can add it from /konto.
            phone=phone if phone_verified else '',
            user_type='registered',
        )
        # No usable password — Vipps Login is the auth.
        user.set_unusable_password()
        user.save()
    else:
        # Existing user — fill in any blanks Vipps just gave us, but don't
        # overwrite values the user has already curated.
        updates: dict = {}
        if not user.name and name:
            updates['name'] = name
        if not user.phone and phone and phone_verified:
            updates['phone'] = phone
        if user.user_type == 'guest':
            # Vipps-verified — promote them to a real registered account.
            updates['user_type'] = 'registered'
        if updates:
            for k, v in updates.items():
                setattr(user, k, v)
            user.save(update_fields=list(updates.keys()))

    VippsIdentity.objects.create(user=user, sub=sub, last_userinfo=userinfo)
    return user


@api_view(['POST'])
@permission_classes([AllowAny])
def vipps_exchange_view(request):
    """Storefront posts the handoff token; we return the normal auth payload.

    This is what the NextAuth credentials provider calls when it sees a
    `vippsToken` field — it gets back the same {access, refresh, user}
    shape as the email/password login.
    """
    token = (request.data.get('token') or '').strip()
    if not token:
        return Response({'detail': 'Mangler token.'}, status=400)

    try:
        decoded = jwt.decode(token, HANDOFF_SECRET, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        return Response({'detail': 'Token utløpt.'}, status=400)
    except jwt.InvalidTokenError:
        return Response({'detail': 'Ugyldig token.'}, status=400)

    if decoded.get('kind') != 'vipps_handoff':
        return Response({'detail': 'Feil token-type.'}, status=400)

    user_id = decoded.get('user_id')
    user = CustomUser.objects.filter(id=user_id).first()
    if not user:
        return Response({'detail': 'Bruker ikke funnet.'}, status=404)

    return Response(AuthResponseSerializer.for_user(user))
