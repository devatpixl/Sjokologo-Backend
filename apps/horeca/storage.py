"""Private storage for customer logos.

`config/urls.py` serves MEDIA_URL unconditionally, and nginx serves /media/ in
production, so a file under MEDIA_ROOT is world-readable by URL. A customer's
logo is confidential artwork. It therefore lives somewhere no serving rule
points at, and reaches the browser only through an authenticated view.
"""
import os
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateLogoStorage(FileSystemStorage):
    """Resolves its location at access time, not at construction time.

    Two bugs live in the obvious alternative:

    1. `FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)` passed as an
       *instance* is serialised into the migration with this machine's
       absolute path baked in, breaking every other environment.
    2. Even passed as a callable, Django evaluates it ONCE when the model field
       is constructed — at import time. That makes the setting impossible to
       override, so a test suite silently writes real customer logo files into
       the repository and leaves them there.

    Overriding the properties is what makes the setting actually authoritative.
    """

    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def private_logo_storage():
    """A callable, so the migration references this function by import path
    rather than embedding a filesystem path."""
    return PrivateLogoStorage(base_url=None)


def logo_upload_to(instance, filename: str) -> str:
    """An unguessable path that contains none of the customer's filename.

    Both path traversal and information leaks start with trusting an uploaded
    name, so the only thing kept from it is the extension (capped, lowercased).
    The original name is stored on the model for display and download instead.
    """
    ext = Path(filename).suffix.lower()[:8]
    return f'horeca/logos/{instance.company_id}/{uuid.uuid4().hex}{ext}'
