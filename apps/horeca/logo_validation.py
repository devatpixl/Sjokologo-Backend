"""Logo file validation (K-25, K-26, K-27).

Every check is on file **content**. Neither the extension nor the browser's
`content_type` is trusted for anything except labelling `ai` apart from `pdf`,
because a `.exe` renamed `.png` arrives with `image/png` attached and a cheerful
smile.

Vectors are exempt from the pixel floor, which is the whole point of K-27 — a
vector has no pixels, and rejecting one for being "too small" would send a
customer away to downscale artwork that was already perfect.
"""
import hashlib
from dataclasses import dataclass

from django.conf import settings
from PIL import Image
from rest_framework.exceptions import ValidationError

# A 25 MB PNG can decompress to gigabytes. Pillow warns above this and raises
# DecompressionBombError above twice it; both are caught below.
Image.MAX_IMAGE_PIXELS = 200_000_000

RASTER = 'raster'
VECTOR = 'vector'

ACCEPTED_LABEL = 'JPG, PNG, PDF, SVG, EPS eller AI'

# Markup that makes an SVG executable or able to reach off-origin.
_SVG_FORBIDDEN = (
    b'<script', b'javascript:', b'<foreignobject',
    b'<!doctype', b'<!entity', b'onload=', b'onerror=', b'onclick=',
)


@dataclass(frozen=True)
class LogoProbe:
    detected_format: str
    kind: str
    byte_size: int
    checksum_sha256: str
    width_px: int | None
    height_px: int | None


def _sniff(head: bytes, filename: str) -> tuple[str, str] | None:
    """(detected_format, kind) from magic bytes, or None if unrecognised."""
    lower = filename.lower()

    if head.startswith(b'\xff\xd8\xff'):
        return 'jpeg', RASTER
    if head.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png', RASTER
    if head.startswith(b'%PDF-'):
        # A modern .ai file IS a PDF and is byte-identical to one. The extension
        # is the only way to tell them apart, and it only affects the label.
        return ('ai' if lower.endswith('.ai') else 'pdf'), VECTOR
    if head.startswith(b'%!PS-Adobe') or head.startswith(b'\xc5\xd0\xd3\xc6'):
        # Legacy .ai is PostScript, so it lands here with EPS.
        return ('ai' if lower.endswith('.ai') else 'eps'), VECTOR
    if b'<svg' in head[:4096].lower():
        return 'svg', VECTOR
    return None


def probe_logo(upload) -> LogoProbe:
    """Validate an uploaded file and return what we learned about it.

    Raises ValidationError with a Norwegian message that says what to do —
    K-66 asks for errors that tell the user how to fix the problem, not just
    that something went wrong.
    """
    size = upload.size or 0
    if size == 0:
        raise ValidationError({'file': 'Filen er tom.'})

    max_bytes = settings.HORECA_LOGO_MAX_BYTES
    if size > max_bytes:
        # Say the actual size. "Too big" alone makes people retry the same file.
        raise ValidationError({'file': (
            f'Filen er {size / 1024 / 1024:.1f} MB. '
            f'Maks er {max_bytes // 1024 // 1024} MB.'
        )})

    upload.seek(0)
    head = upload.read(8192)
    sniffed = _sniff(head, upload.name or '')
    if sniffed is None:
        raise ValidationError({'file': f'Vi støtter {ACCEPTED_LABEL}.'})
    detected_format, kind = sniffed

    # Checksum the whole file while streaming, so a 25 MB logo is never held in
    # memory twice.
    upload.seek(0)
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    checksum = digest.hexdigest()

    width = height = None

    if detected_format == 'svg':
        upload.seek(0)
        body = upload.read(max_bytes).lower()
        for token in _SVG_FORBIDDEN:
            if token in body:
                # Rejected rather than sanitised: a half-cleaned SVG is worse
                # than a clear error, and the customer can simply re-export.
                raise ValidationError({'file': (
                    'SVG-filen inneholder skript eller eksterne referanser. '
                    'Eksporter den på nytt som en ren vektorfil.'
                )})

    elif kind == RASTER:
        upload.seek(0)
        try:
            with Image.open(upload) as img:
                img.verify()
            upload.seek(0)
            with Image.open(upload) as img:
                width, height = img.size
        except Image.DecompressionBombError:
            raise ValidationError({'file': 'Bildet er for stort til å behandles.'})
        except Exception:
            raise ValidationError({'file': 'Kunne ikke lese bildefilen.'})

        # The LONG edge, not the short one. The logo is printed into a strip
        # seven chocolate pieces wide and one tall — roughly 7:1 — so the
        # best-suited artwork for this product is a wide wordmark, which by
        # definition has a small short edge. Testing min() rejected a 3000x600
        # wordmark (ample detail for the strip) while accepting a 1000x1000
        # square that fills only a seventh of it: exactly backwards.
        #
        # Loosening is safe because this is a first filter, not the last line
        # of defence — K-28 lands every upload as `pending` and nothing reaches
        # the kitchen without a human approving it.
        floor = settings.HORECA_LOGO_MIN_RASTER_PX
        if max(width, height) < floor:
            raise ValidationError({'file': (
                f'Bildet er {width} × {height} piksler. Vi trenger minst '
                f'{floor} piksler på den lengste siden for at trykket på '
                'spisearket skal bli skarpt. En vektorfil (PDF, SVG, EPS '
                'eller AI) går alltid bra.'
            )})

    upload.seek(0)
    return LogoProbe(
        detected_format=detected_format,
        kind=kind,
        byte_size=size,
        checksum_sha256=checksum,
        width_px=width,
        height_px=height,
    )
