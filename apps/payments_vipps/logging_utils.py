"""Helpers that scrub sensitive values from log records before they're emitted.

The Vipps integration handles access tokens, signing secrets, and full Authorization
headers. None of those should ever land in logs. Use ``redact_headers`` before
logging request/response metadata, and ``safe_repr`` for ad-hoc structures.
"""
from typing import Mapping


SENSITIVE_HEADER_NAMES = frozenset({
    'authorization',
    'ocp-apim-subscription-key',
    'cookie',
    'set-cookie',
    'x-vipps-secret',
})

SENSITIVE_BODY_KEYS = frozenset({
    'access_token',
    'client_secret',
    'secret',
    'token',
    'password',
})


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a shallow copy of ``headers`` with sensitive values replaced by `***`."""
    return {
        k: ('***' if k.lower() in SENSITIVE_HEADER_NAMES else v)
        for k, v in headers.items()
    }


def redact_body(payload: object) -> object:
    """Recursively replace sensitive keys in dict/list payloads."""
    if isinstance(payload, dict):
        return {
            k: ('***' if k.lower() in SENSITIVE_BODY_KEYS else redact_body(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact_body(v) for v in payload]
    return payload
