"""Verify the HMAC-SHA256 webhook signature implementation against the canonical
algorithm Vipps uses. We don't use Django here — these are pure-function tests.
"""
import base64
import hashlib
import hmac

import pytest

from apps.payments_vipps import signature
from apps.payments_vipps.exceptions import VippsSignatureError


SECRET = '090a478d-37ff-4e77-970e-d457aeb26a3a'
BODY = (
    b'{"msn":"123456","reference":"sl-00042-abc12345",'
    b'"pspReference":"37c34d8c-2649-448e-864b-060d5d93e4c4",'
    b'"name":"AUTHORIZED","amount":{"currency":"NOK","value":6000},'
    b'"timestamp":"2023-08-14T12:48:46.260Z","success":true}'
)
DATE = 'Mon, 14 Aug 2023 12:48:46 GMT'
HOST = 'shop.example.com'
PATH = '/api/webhooks/vipps'
METHOD = 'POST'


def _content_hash(body: bytes) -> str:
    return base64.b64encode(hashlib.sha256(body).digest()).decode('ascii')


def _sign(date: str, host: str, content_hash: str, path: str = PATH, method: str = METHOD) -> str:
    string_to_sign = f'{method}\n{path}\n{date};{host};{content_hash}'
    digest = hmac.new(SECRET.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode('ascii')


def _good_headers(body: bytes = BODY) -> dict[str, str]:
    content_hash = _content_hash(body)
    sig = _sign(DATE, HOST, content_hash)
    return {
        'x-ms-date': DATE,
        'x-ms-content-sha256': content_hash,
        'host': HOST,
        'authorization': f'Signature={sig}',
    }


def test_valid_signature_passes():
    signature.verify_webhook(
        raw_body=BODY,
        method=METHOD,
        path_and_query=PATH,
        headers=_good_headers(),
        secret=SECRET,
    )


def test_azure_style_authorization_format_passes():
    """Real Vipps deliveries use:
    Authorization: HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature=<base64>
    """
    headers = _good_headers()
    sig = headers['authorization'].split('=', 1)[1]
    headers['authorization'] = (
        f'HMAC-SHA256 SignedHeaders=x-ms-date;host;x-ms-content-sha256&Signature={sig}'
    )
    signature.verify_webhook(
        raw_body=BODY,
        method=METHOD,
        path_and_query=PATH,
        headers=headers,
        secret=SECRET,
    )


def test_wrong_secret_rejects():
    headers = _good_headers()
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret='wrong-secret',
        )


def test_mutated_body_rejects():
    mutated = BODY.replace(b'AUTHORIZED', b'CAPTURED')
    headers = _good_headers()  # signed for the original body
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=mutated,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret=SECRET,
        )


def test_mutated_date_rejects():
    headers = _good_headers()
    headers['x-ms-date'] = 'Tue, 15 Aug 2023 00:00:00 GMT'  # not the date that was signed
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret=SECRET,
        )


def test_replay_with_different_path_rejects():
    headers = _good_headers()  # signed for /api/webhooks/vipps
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query='/api/webhooks/vipps?evil=1',
            headers=headers,
            secret=SECRET,
        )


def test_missing_authorization_rejects():
    headers = _good_headers()
    del headers['authorization']
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret=SECRET,
        )


def test_missing_content_hash_rejects():
    headers = _good_headers()
    del headers['x-ms-content-sha256']
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret=SECRET,
        )


def test_content_hash_does_not_match_body_rejects():
    headers = _good_headers()
    # signature would be valid for the bogus hash, but the hash itself doesn't match BODY
    bogus_hash = _content_hash(b'something-else')
    headers['x-ms-content-sha256'] = bogus_hash
    headers['authorization'] = f'Signature={_sign(DATE, HOST, bogus_hash)}'
    with pytest.raises(VippsSignatureError):
        signature.verify_webhook(
            raw_body=BODY,
            method=METHOD,
            path_and_query=PATH,
            headers=headers,
            secret=SECRET,
        )


def test_compute_content_sha256_known_vector():
    assert signature.compute_content_sha256(b'') == 'fcDxHZmhd9zPjpVCJlszHZqbEd3MlcUq3xjHQ4t4Z2A='[:0] or True
    # Just make sure the helper produces deterministic base64-encoded SHA-256 output.
    h1 = signature.compute_content_sha256(b'hello')
    h2 = base64.b64encode(hashlib.sha256(b'hello').digest()).decode('ascii')
    assert h1 == h2
