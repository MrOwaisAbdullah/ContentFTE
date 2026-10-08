"""
lib/image_provenance.py — IPTC `TrainedAlgorithmicMedia` provenance tags

Spec §5.9 / Playbook §12: every AI-generated image carries IPTC provenance
metadata at zero generation cost — a forward-looking signal as answer
engines start distinguishing AI imagery.

Mechanism (per IPTC's own guidance, 2024:
https://iptc.org/news/iptc-publishes-metadata-guidance-for-ai-generated-synthetic-media):
add "Digital Source Type" = trainedAlgorithmicMedia to the image's XMP
packet:

    Iptc4xmpExt:DigitalSourceType =
        http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia

XMP is the IPTC-recommended carrier (alternative is a C2PA manifest, which
needs a signing certificate — out of scope for Phase 1).

Formats handled, pure stdlib (no new dependencies):
- JPEG: XMP APP1 segment (identifier "http://ns.adobe.com/xap/1.0/"),
  inserted before the start-of-scan; an existing XMP APP1 is replaced.
- PNG:  uncompressed iTXt chunk (keyword "XML:com.adobe.xmp") right after
  IHDR; an existing XMP iTXt chunk is left alone (idempotent).

Every function is best-effort and never raises: a provenance-tag failure
must never fail an image generation that already succeeded.
"""

import logging
import os
import struct
import zlib
from typing import Optional

logger = logging.getLogger(__name__)

TRAINED_ALGORITHMIC_MEDIA_URI = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
)

_JPEG_XMP_ID = b"http://ns.adobe.com/xap/1.0/\x00"
_PNG_XMP_KEYWORD = b"XML:com.adobe.xmp"

_XMP_PACKET = (
    '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="ContentFTE image pipeline">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '  <rdf:Description rdf:about=""\n'
    '    xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"\n'
    f'    Iptc4xmpExt:DigitalSourceType="{TRAINED_ALGORITHMIC_MEDIA_URI}"/>\n'
    ' </rdf:RDF>\n'
    '</x:xmpmeta>\n'
    '<?xpacket end="w"?>'
)


def build_xmp_packet() -> bytes:
    """The XMP packet bytes written into JPEG APP1 / PNG iTXt."""
    return _XMP_PACKET.encode("utf-8")


def has_trained_algorithmic_media(data: bytes) -> bool:
    """True if the raw file bytes already carry the provenance URI."""
    if not data:
        return False
    return TRAINED_ALGORITHMIC_MEDIA_URI.encode("utf-8") in data


def _is_jpeg(data: bytes) -> bool:
    return data[:2] == b"\xff\xd8"


def _is_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def _jpeg_segment(marker: int, payload: bytes) -> bytes:
    """One length-prefixed JPEG segment: marker + length + payload."""
    length = len(payload) + 2
    if length > 0xFFFF:
        raise ValueError("JPEG segment too large")
    return b"\xff" + bytes([marker]) + struct.pack(">H", length) + payload


def _jpeg_with_xmp(data: bytes, xmp: bytes) -> Optional[bytes]:
    """Returns the JPEG with an XMP APP1 segment inserted before SOS,
    replacing any existing XMP APP1. None if the input is not a parseable
    JPEG (caller falls back / gives up)."""
    if not _is_jpeg(data):
        return None
    app1_xmp = _jpeg_segment(0xE1, _JPEG_XMP_ID + xmp)
    i = 2
    insert_at: Optional[int] = None
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None  # desynced: not a well-formed segment stream
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0x01,) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:  # EOI without SOS seen — malformed for our purpose
            return None
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        seg_end = i + 2 + seg_len
        if seg_end > len(data):
            return None
        if marker == 0xDA:  # SOS: image data starts here — insert before it
            insert_at = i
            break
        if marker == 0xE1 and data[i + 4 : i + 4 + len(_JPEG_XMP_ID)] == _JPEG_XMP_ID:
            # Existing XMP APP1: drop it (replace with ours below).
            data = data[:i] + data[seg_end:]
            continue
        i = seg_end
    if insert_at is None:
        # No SOS found (truncated file): append before EOI if present.
        eoi = data.rfind(b"\xff\xd9")
        if eoi == -1:
            return None
        insert_at = eoi
    return data[:insert_at] + app1_xmp + data[insert_at:]


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _png_with_xmp(data: bytes, xmp: bytes) -> Optional[bytes]:
    """Returns the PNG with an uncompressed XMP iTXt chunk after IHDR.
    None if the input is not a parseable PNG."""
    if not _is_png(data):
        return None
    if _PNG_XMP_KEYWORD in data:
        return data  # already carries an XMP chunk — idempotent no-op
    # keyword \0 compressionFlag compressionMethod lang\0 translated\0 text
    payload = _PNG_XMP_KEYWORD + b"\x00\x00\x00\x00\x00" + xmp
    itxt = _png_chunk(b"iTXt", payload)
    # Walk to the end of the first chunk (IHDR) and insert right after it.
    pos = 8
    if pos + 8 > len(data):
        return None
    first_len = struct.unpack(">I", data[pos : pos + 4])[0]
    first_type = data[pos + 4 : pos + 8]
    if first_type != b"IHDR":
        return None
    after_ihdr = pos + 12 + first_len
    if after_ihdr > len(data):
        return None
    return data[:after_ihdr] + itxt + data[after_ihdr:]


def tag_trained_algorithmic_media(path: str) -> bool:
    """Write the IPTC trainedAlgorithmicMedia Digital Source Type into the
    image file at `path` (JPEG/PNG). Returns True if the file now carries
    the tag (including when it already did), False otherwise. Never raises;
    a tagging failure only logs — the image itself is still usable."""
    try:
        if not path or not os.path.exists(path):
            return False
        with open(path, "rb") as fh:
            data = fh.read()
        if not data:
            return False
        if has_trained_algorithmic_media(data):
            return True
        xmp = build_xmp_packet()
        if _is_jpeg(data):
            updated = _jpeg_with_xmp(data, xmp)
        elif _is_png(data):
            updated = _png_with_xmp(data, xmp)
        else:
            logger.info(f"Unsupported format for provenance tag, skipping: {path}")
            return False
        if updated is None:
            logger.warning(f"Could not inject XMP provenance tag into {path}")
            return False
        tmp_path = f"{path}.iptc-tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(updated)
        os.replace(tmp_path, path)
        return True
    except Exception as e:
        logger.warning(f"Provenance tagging failed for {path}: {e}")
        return False
