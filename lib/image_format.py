"""Detect an image's real format from its bytes.

Cloudflare Workers AI returns JPEG for the flux-2 family regardless of the
requested output, so writing that response into a ``.png`` temp file made
every downstream consumer trust an extension that did not match the bytes:
Sanity uploaded the asset with ``Content-Type: image/png``, and the vision
call wrapped JPEG data in ``data:image/png;base64,``. Sniff the magic bytes
instead of guessing from the path.
"""

from __future__ import annotations

MIME_BY_FORMAT = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}

EXT_BY_FORMAT = {
    "png": ".png",
    "jpeg": ".jpg",
    "webp": ".webp",
    "gif": ".gif",
    "bmp": ".bmp",
}

_SNIFF_BYTES = 16


def sniff_image_format(data: bytes) -> str:
    """Return one of png/jpeg/webp/gif/bmp, or ``"unknown"``."""
    if not data:
        return "unknown"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:2] == b"BM":
        return "bmp"
    return "unknown"


def sniff_mime(data: bytes, fallback: str = "image/png") -> str:
    return MIME_BY_FORMAT.get(sniff_image_format(data), fallback)


def sniff_ext(data: bytes, fallback: str = ".png") -> str:
    return EXT_BY_FORMAT.get(sniff_image_format(data), fallback)


def sniff_file(path: str, fallback: str = "image/png") -> str:
    """MIME type for a local file, decided by content rather than extension."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError:
        return fallback
    return sniff_mime(head, fallback)


def sniff_file_ext(path: str, fallback: str = ".png") -> str:
    try:
        with open(path, "rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError:
        return fallback
    return sniff_ext(head, fallback)
