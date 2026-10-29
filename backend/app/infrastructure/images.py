"""Re-encodes uploaded images: drops EXIF/GPS and every other metadata, applies the camera's rotation, caps the size."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 2000  # px: plenty for a catalog; phone photos are often 4000+
Image.MAX_IMAGE_PIXELS = 40_000_000  # a "decompression bomb" (tiny file, huge image) fails instead of eating the memory
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def clean_image(data: bytes, content_type: str) -> bytes | None:
    """The same picture without metadata, or None when it isn't a readable image of that type."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            if Image.MIME.get(img.format) != content_type:
                return None
            img = ImageOps.exif_transpose(img)  # keep the photo upright once the EXIF orientation is gone
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            if content_type == "image/jpeg" and img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            # Saving without exif=/icc_profile=/pnginfo= writes no metadata at all
            img.save(out, FORMATS[content_type], **({"quality": 88, "optimize": True} if content_type != "image/png" else {"optimize": True}))
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return None


def logo_png(data: bytes) -> bytes | None:
    """The business logo as a small PNG without metadata (PDFs embed PNG, not WebP), or None when it isn't an image."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            if Image.MIME.get(img.format) not in FORMATS:
                return None
            img = ImageOps.exif_transpose(img)
            img.thumbnail((600, 600))
            if img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA")
            out = io.BytesIO()
            img.save(out, "PNG", optimize=True)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return None
