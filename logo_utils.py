"""
Credential Protocol — logo uploads

Turns an uploaded image into a small, safe `data:` URI that can be stored in
settings and embedded straight into the card file. Pictures people upload are
untrusted input, so:

  * only real PNG / JPEG / GIF / WEBP pictures are accepted (checked by
    actually decoding them, not by trusting the file name or the browser's
    claim about the type) — no SVG, no HTML dressed up as an image;
  * the picture is re-encoded, which drops any metadata or oddities;
  * it's shrunk to at most MAX_SIDE pixels, since a logo is shown at roughly
    220 px wide on a card — a phone photo would just bloat every card and
    email and the settings file.

With Pillow missing (it normally comes with reportlab), only PNG/JPEG/GIF/WEBP
under MAX_BYTES_NO_PILLOW are accepted as-is, after a signature check.
"""

import base64
from io import BytesIO

MAX_UPLOAD_BYTES    = 5 * 1024 * 1024    # refuse anything bigger before even decoding it
MAX_SIDE            = 600                # px, longest side after shrinking
MAX_PIXELS          = 25_000_000         # guards against decompression bombs
MAX_BYTES_NO_PILLOW = 600 * 1024

_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff",      "image/jpeg"),
    (b"GIF87a",            "image/gif"),
    (b"GIF89a",            "image/gif"),
)


def _sniff(raw: bytes):
    for sig, mime in _SIGNATURES:
        if raw.startswith(sig):
            return mime
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _data_uri(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def process_logo(raw: bytes) -> tuple:
    """Returns (data_uri, "") on success or ("", reason for the creator)."""
    if not raw:
        return "", ""
    if len(raw) > MAX_UPLOAD_BYTES:
        return "", "That logo file is too big (over 5 MB). Use a smaller picture."
    mime = _sniff(raw)
    if mime is None:
        return "", "That file isn't a PNG, JPG, GIF or WEBP picture, so it wasn't used."

    try:
        from PIL import Image
    except ImportError:
        if len(raw) > MAX_BYTES_NO_PILLOW:
            return "", "That logo is too big (over 600 KB). Use a smaller picture."
        return _data_uri(raw, mime), ""

    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        img = Image.open(BytesIO(raw))             # reads only the header
        if img.size[0] * img.size[1] > MAX_PIXELS:   # checked BEFORE decoding (Pillow itself only warns up to 2x)
            return "", "That picture is too large (too many pixels). Use a smaller one."
        img.load()                       # decode fully: proves it's really a picture
        has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        if img.mode == "P":
            img = img.convert("RGBA" if has_alpha else "RGB")
        elif img.mode not in ("RGB", "RGBA", "L", "LA"):
            img = img.convert("RGBA" if has_alpha else "RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        out = BytesIO()
        if mime == "image/jpeg" and not has_alpha:
            img.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
            return _data_uri(out.getvalue(), "image/jpeg"), ""
        img.save(out, "PNG", optimize=True)
        return _data_uri(out.getvalue(), "image/png"), ""
    except Exception as e:   # includes DecompressionBombError and corrupt files
        if "decompression" in type(e).__name__.lower() or "pixels" in str(e).lower():
            return "", "That picture is too large (too many pixels). Use a smaller one."
        return "", "That picture couldn't be read, so it wasn't used."


# A card background is bigger than a logo: it fills the whole card, which is
# shown about 380 px wide (so ~760 px on a sharp phone screen). It is stored as
# a JPEG, because every card file carries its own copy of the picture.
BG_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
BG_MAX_SIDE         = 1000
BG_MAX_BYTES_NO_PILLOW = 400 * 1024


def process_background(raw: bytes) -> tuple:
    """A card background upload -> (data: URI of a shrunk JPEG, "") or
    ("", reason for the creator). Same checks as process_logo (the picture is
    really decoded, never trusted by name), then it is turned the right way up
    (phone photos), flattened onto black if it has transparency, shrunk to
    BG_MAX_SIDE and saved as a JPEG."""
    if not raw:
        return "", ""
    if len(raw) > BG_MAX_UPLOAD_BYTES:
        return "", "That picture is too big (over 10 MB). Use a smaller one."
    mime = _sniff(raw)
    if mime is None:
        return "", "That file isn't a PNG, JPG, GIF or WEBP picture, so it wasn't used."
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if len(raw) > BG_MAX_BYTES_NO_PILLOW:
            return "", "That picture is too big (over 400 KB). Use a smaller one."
        return _data_uri(raw, mime), ""
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        img = Image.open(BytesIO(raw))
        if img.size[0] * img.size[1] > MAX_PIXELS:
            return "", "That picture is too large (too many pixels). Use a smaller one."
        img.load()
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            img = img.convert("RGBA")
            base = Image.new("RGB", img.size, (0, 0, 0))
            base.paste(img, mask=img.split()[-1])
            img = base
        else:
            img = img.convert("RGB")
        if max(img.size) > BG_MAX_SIDE:
            img.thumbnail((BG_MAX_SIDE, BG_MAX_SIDE), Image.LANCZOS)
        out = BytesIO()
        img.save(out, "JPEG", quality=80, optimize=True, progressive=True)
        return _data_uri(out.getvalue(), "image/jpeg"), ""
    except Exception as e:
        if "decompression" in type(e).__name__.lower() or "pixels" in str(e).lower():
            return "", "That picture is too large (too many pixels). Use a smaller one."
        return "", "That picture couldn't be read, so it wasn't used."


def is_logo_data_uri(value) -> bool:
    """True for a data: URI of one of the allowed image types — used before
    a stored value is ever written into a page."""
    return isinstance(value, str) and value.startswith(
        ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/gif;base64,", "data:image/webp;base64,"))
