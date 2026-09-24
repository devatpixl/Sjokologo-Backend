"""K-25, K-26, K-27 — and the checks that are about safety rather than print
quality.

Everything here uses real bytes rather than mocks, because the whole point of
the validator is that it does not trust the extension or the browser's
content-type.
"""
import io

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.exceptions import ValidationError

from apps.horeca.logo_validation import probe_logo
from apps.horeca.models import Logo

pytestmark = pytest.mark.django_db


def _png(width=1200, height=1200, name='logo.png'):
    buf = io.BytesIO()
    Image.new('RGBA', (width, height), (0, 0, 0, 0)).save(buf, format='PNG')
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type='image/png')


def _upload(api, upload, name='Hovedlogo'):
    return api.post(reverse('horeca-logos'),
                    {'file': upload, 'name': name}, format='multipart')


# ── accepted ────────────────────────────────────────────────────────────────

def test_a_large_png_is_accepted(api, company):
    res = _upload(api, _png())
    assert res.status_code == 201, res.data
    assert res.data['status'] == Logo.Status.PENDING, 'K-28 — review comes first'
    assert res.data['width_px'] == 1200
    assert res.data['kind'] == 'raster'


def test_a_wide_wordmark_is_accepted_even_though_it_is_short(api, company):
    """Regression. The floor used to be measured on the SHORT edge, which
    rejected exactly the artwork this product wants: the logo prints into a
    strip seven pieces wide and one tall, so a wide wordmark is the ideal
    shape, and a wide wordmark has a small short edge by definition.

    3000 x 600 carries far more detail across a 7:1 strip than the 1000 x 1000
    square the old rule happily accepted.
    """
    res = _upload(api, _png(3000, 600))
    assert res.status_code == 201, res.data
    assert res.data['width_px'] == 3000


def test_a_file_too_small_on_both_edges_is_still_refused(api, company):
    """The loosening must not turn the floor off. 537 x 372 is a web-sized
    logo — roughly 135 DPI once printed — and it still cannot be used."""
    res = _upload(api, _png(537, 372))
    assert res.status_code == 400
    detail = str(res.data['file'])
    assert '537' in detail and '372' in detail, 'say the real size'
    assert 'lengste siden' in detail, 'say WHICH edge is measured, or it reads as a square rule'


def test_a_small_vector_is_accepted_because_vectors_have_no_pixels(api):
    """K-27's exemption. Rejecting a vector for being 'too small' would send a
    customer away to fix artwork that was already perfect."""
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '\
          b'width="10" height="10"><rect width="10" height="10"/></svg>'
    res = _upload(api, SimpleUploadedFile('logo.svg', svg,
                                          content_type='image/svg+xml'))
    assert res.status_code == 201, res.data
    assert res.data['kind'] == 'vector'
    assert res.data['width_px'] is None


def test_a_pdf_is_treated_as_a_vector(api):
    res = _upload(api, SimpleUploadedFile(
        'logo.pdf', b'%PDF-1.7\n%stuff\n', content_type='application/pdf',
    ))
    assert res.status_code == 201
    assert res.data['detected_format'] == 'pdf'


def test_an_ai_file_is_labelled_ai_even_though_it_is_a_pdf(api):
    """A modern .ai IS a PDF and is byte-identical. The extension is the only
    disambiguator, and it only affects the label."""
    res = _upload(api, SimpleUploadedFile(
        'logo.ai', b'%PDF-1.7\n%stuff\n', content_type='application/pdf',
    ))
    assert res.status_code == 201
    assert res.data['detected_format'] == 'ai'
    assert res.data['kind'] == 'vector'


# ── refused, each for its own reason ────────────────────────────────────────

def test_a_raster_below_the_floor_is_refused_with_its_actual_size(api):
    res = _upload(api, _png(900, 900))
    assert res.status_code == 400
    detail = str(res.data['file'])
    assert '900' in detail, 'say the real size, or people retry the same file'
    assert '1000' in detail
    assert 'vektorfil' in detail.lower(), 'offer the way out'


def test_a_text_file_renamed_png_is_refused(api):
    """Proves the check is on magic bytes, not the extension or content-type —
    both of which the client controls."""
    res = _upload(api, SimpleUploadedFile(
        'logo.png', b'this is just text, not an image at all',
        content_type='image/png',
    ))
    assert res.status_code == 400
    assert 'støtter' in str(res.data['file']).lower()


def test_an_empty_file_is_refused(api):
    res = _upload(api, SimpleUploadedFile('logo.png', b'',
                                          content_type='image/png'))
    assert res.status_code == 400


def test_an_svg_containing_script_is_refused_not_sanitised(api):
    """An SVG served from our own origin is a scripting vector. A half-cleaned
    file is worse than a clear error — the customer can simply re-export."""
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg"><script>'
           b'alert(1)</script></svg>')
    res = _upload(api, SimpleUploadedFile('logo.svg', svg,
                                          content_type='image/svg+xml'))
    assert res.status_code == 400
    assert 'skript' in str(res.data['file']).lower()


def test_an_svg_with_an_onload_handler_is_refused(api):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"></svg>'
    res = _upload(api, SimpleUploadedFile('logo.svg', svg,
                                          content_type='image/svg+xml'))
    assert res.status_code == 400


def test_an_oversized_file_is_refused_with_both_numbers(settings_max_1mb, api):
    big = SimpleUploadedFile('logo.png', b'\x89PNG\r\n\x1a\n' + b'x' * (2 * 1024 * 1024),
                             content_type='image/png')
    res = _upload(api, big)
    assert res.status_code == 400
    detail = str(res.data['file'])
    assert 'MB' in detail
    assert 'Maks' in detail


@pytest.fixture
def settings_max_1mb(settings):
    settings.HORECA_LOGO_MAX_BYTES = 1024 * 1024
    return settings


def test_re_uploading_a_rejected_file_returns_the_original_reason(api, company):
    upload = _png()
    res = _upload(api, upload)
    logo = Logo.objects.get(pk=res.data['id'])
    logo.status = Logo.Status.REJECTED
    logo.rejection_reason = 'Strekene er for tynne for spiseark.'
    logo.save()

    again = _upload(api, _png())  # identical bytes → identical checksum
    assert again.status_code == 400
    assert 'tynne' in str(again.data['file']), (
        'answer with the original reason, not a second pending review'
    )


# ── privacy: the file must not be reachable under /media/ ───────────────────

def test_logo_files_are_stored_outside_media_root(api):
    res = _upload(api, _png())
    logo = Logo.objects.get(pk=res.data['id'])
    path = logo.file.path

    assert str(settings.MEDIA_ROOT) not in path, (
        'config/urls.py serves MEDIA_ROOT unconditionally — a logo there is '
        'readable by anyone who guesses the URL'
    )
    assert str(settings.PRIVATE_MEDIA_ROOT) in path


def test_downloading_a_logo_never_serves_it_inline(api):
    """An inline SVG from our origin would execute. Always an attachment."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    res = _upload(api, SimpleUploadedFile('logo.svg', svg,
                                          content_type='image/svg+xml'))
    download = api.get(reverse('horeca-logo-file', args=[res.data['id']]))
    assert download.status_code == 200
    assert download['Content-Type'] == 'application/octet-stream'
    assert 'attachment' in download['Content-Disposition']
    assert download['X-Content-Type-Options'] == 'nosniff'


def test_signed_url_works_and_expires(api, monkeypatch):
    res = _upload(api, _png())
    signed = api.get(reverse('horeca-logo-signed-url', args=[res.data['id']]))
    assert signed.status_code == 200
    url = signed.data['url']

    # Absolute, or an <img src> on the storefront origin 404s (see the view).
    assert url.startswith('http'), 'the browser needs an absolute URL'
    path = url.split('/api/')[1]
    assert api.get('/api/' + path).status_code == 200

    # Past max_age the same token must stop working.
    import apps.horeca.views as views
    monkeypatch.setattr(views, 'LOGO_URL_MAX_AGE', -1)
    assert api.get('/api/' + path).status_code == 404


def test_probe_rejects_directly_too(api):
    """The validator is usable without HTTP, so it can be unit-tested and
    reused by an admin import path later."""
    with pytest.raises(ValidationError):
        probe_logo(SimpleUploadedFile('x.png', b'nope', content_type='image/png'))
