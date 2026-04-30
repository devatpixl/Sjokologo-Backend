"""HMAC-SHA256 verification of incoming Vipps webhook signatures.

Vipps signs each webhook delivery using a canonical string built from the
request method, path, x-ms-date, Host, and a SHA-256 hash of the raw body.
The signing key is the secret returned at webhook registration time.

Verification is two steps:
    1. Hash the raw request body with SHA-256, base64-encode, and compare
       against the value of the ``x-ms-content-sha256`` header.
    2. Build the signing string ``METHOD\\nPATH\\nDATE;HOST;HASH``,
       HMAC-SHA256 it with the secret, base64-encode, and compare against
       the ``Signature=`` value parsed from the ``Authorization`` header.

Both comparisons MUST be constant-time to avoid timing oracles.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

from .exceptions import VippsSignatureError


def compute_content_sha256(raw_body: bytes) -> str:
    """Return the base64-encoded SHA-256 digest of ``raw_body``."""
    digest = hashlib.sha256(raw_body).digest()
    return base64.b64encode(digest).decode('ascii')


def build_signing_string(
    method: str,
    path_and_query: str,
    date_header: str,
    host_header: str,
    content_sha256_header: str,
) -> str:
    """Build the canonical signing string Vipps signs.

    Format: ``"{METHOD}\\n{PATH_AND_QUERY}\\n{x-ms-date};{Host};{x-ms-content-sha256}"``
    """
    return (
        f'{method.upper()}\n'
        f'{path_and_query}\n'
        f'{date_header};{host_header};{content_sha256_header}'
    )


def compute_signature(signing_string: str, secret: str) -> str:
    """HMAC-SHA256 the signing string with the secret, base64-encoded."""
    digest = hmac.new(
        secret.encode('utf-8'),
        signing_string.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode('ascii')


def parse_signature_header(authorization_header: str) -> str:
    """Extract the base64 signature value from a Vipps Authorization header.

    Vipps sends the Azure-style form:
        ``HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature=<base64>``

    We also accept the simpler ``Signature=<base64>`` form defensively. In
    either shape we pull out the value to the right of ``Signature=`` (up to
    the next ``&`` or end of string).
    """
    if not authorization_header:
        raise VippsSignatureError('Missing Authorization header')
    header = authorization_header.strip()
    marker = 'signature='
    idx = header.lower().find(marker)
    if idx == -1:
        raise VippsSignatureError('Unrecognised Authorization header format')
    value = header[idx + len(marker):]
    # Stop at the next & if present (some impls put extra params after Signature).
    amp = value.find('&')
    if amp != -1:
        value = value[:amp]
    return value.strip()


def verify_webhook(
    *,
    raw_body: bytes,
    method: str,
    path_and_query: str,
    headers: dict[str, str],
    secret: str,
) -> None:
    """Verify a Vipps webhook signature. Raises VippsSignatureError on mismatch.

    ``headers`` keys must be lowercased. Required keys: ``x-ms-date``,
    ``x-ms-content-sha256``, ``host``, ``authorization``.
    """
    try:
        date_header = headers['x-ms-date']
        provided_content_hash = headers['x-ms-content-sha256']
        host_header = headers['host']
        auth_header = headers['authorization']
    except KeyError as exc:
        raise VippsSignatureError(f'Missing required signature header: {exc.args[0]}')

    # Step 1: verify the body hash matches what was signed.
    expected_content_hash = compute_content_sha256(raw_body)
    if not hmac.compare_digest(expected_content_hash, provided_content_hash):
        raise VippsSignatureError('Body hash does not match x-ms-content-sha256')

    # Step 2: verify the HMAC over the canonical string.
    signing_string = build_signing_string(
        method=method,
        path_and_query=path_and_query,
        date_header=date_header,
        host_header=host_header,
        content_sha256_header=provided_content_hash,
    )
    expected_signature = compute_signature(signing_string, secret)
    provided_signature = parse_signature_header(auth_header)

    if not hmac.compare_digest(expected_signature, provided_signature):
        raise VippsSignatureError('HMAC signature mismatch')
