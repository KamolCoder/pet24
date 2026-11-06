import io
from pathlib import Path

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

FULL_SIZE = 1200
THUMB_SIZE = 400


def _to_webp(img: Image.Image, size: int, quality: int) -> bytes:
    img = img.copy()
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def make_variants(field_file) -> tuple[ContentFile, ContentFile]:
    """Uploaded image -> (full WebP <=1200px, thumb WebP <=400px). Keeps transparency, fixes EXIF rotation."""
    field_file.seek(0)
    with Image.open(field_file) as src:
        img = ImageOps.exif_transpose(src)
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
        stem = Path(field_file.name).stem[:80]
        full = ContentFile(_to_webp(img, FULL_SIZE, 85), name=f"{stem}.webp")
        thumb = ContentFile(_to_webp(img, THUMB_SIZE, 80), name=f"{stem}.webp")
    return full, thumb
