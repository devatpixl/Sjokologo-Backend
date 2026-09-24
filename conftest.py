"""Test isolation.

Django's own `setup_test_environment()` already swaps the mail backend for
locmem, so tests cannot reach Gmail. What it does NOT do is neutralise this
project's own settings — and several of them are read straight from a
developer's `.env`, which makes a test pass or fail depending on whose machine
it runs on.

`EMAIL_TEST_OVERRIDE` is the sharpest one: in production it rewrites every
recipient to a single address and stamps the original into the subject. A test
asserting `msg.to == ['kunde@example.no']` is correct locally (where it is
empty) and wrong on any machine that has it set. Pin it here, once, rather
than remembering it in every test.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_environment(settings, tmp_path):
    # Recipients must be exactly what the code chose, not a redirect target.
    settings.EMAIL_TEST_OVERRIDE = ''

    # Read from .env in real life; pinned so recipient assertions are stable.
    # Individual tests still override these when that is the thing under test.
    settings.ADMIN_NOTIFY_EMAILS = []

    # Anything written during a test lands in a temp dir, never in the repo's
    # media/ where it would survive the run.
    settings.MEDIA_ROOT = str(tmp_path / 'media')

    # Logo uploads land here. Without this the suite writes real files into the
    # repo's private-media/ and leaves them behind after the run.
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / 'private-media')

    # revalidate_storefront() posts to the Next.js app on product writes. With
    # no secret it is a documented no-op, which is what a test wants.
    settings.REVALIDATE_SECRET = ''

    # The WhatsApp client is a no-op unless fully configured, but be explicit:
    # a test must never try to message a real number.
    settings.WHATSAPP_ENABLED = False
