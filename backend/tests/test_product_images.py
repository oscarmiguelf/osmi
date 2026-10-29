# Integration test: product images (up to 5) stored in the API's uploads volume.
import io
import secrets

from PIL import Image

from app.application.product_image_service import MAX_BYTES, sniff
from tests.test_calendar import A, B, client
from tests.test_purchases import _seed

def _image(fmt, **kw):
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 60, 60)).save(out, fmt, **kw)
    return out.getvalue()


PNG, JPG, WEBP = _image("PNG"), _image("JPEG"), _image("WEBP")


def _gps_photo():
    """A JPEG with GPS coordinates in its EXIF, like a phone photo."""
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (19.0, 26.0, 0.0), 3: "W", 4: (99.0, 8.0, 0.0)}  # GPSInfo
    exif[0x010F] = "Phone maker"
    return _image("JPEG", exif=exif)


def test_sniff():
    assert (sniff(PNG), sniff(JPG), sniff(WEBP)) == ("image/png", "image/jpeg", "image/webp")
    assert sniff(b"<svg xmlns=...>") is None and sniff(b"GIF89a") is None


def test_product_images():
    tag = secrets.token_hex(3)
    product = client.post("/products", json={"name": f"Foto {tag}", "product_type_id": _seed("/product-types", "Product"),
                                             "unit_of_measure_id": _seed("/units", "Unit")}, headers=A).json()
    base = f"/products/{product['id']}/images"
    up = lambda data, name="x.png", h=A: client.post(base, files={"file": (name, data, "image/png")}, headers=h)
    try:
        # Type from the bytes, not from the name or the browser; size limit; permission
        assert up(b"hello", "x.png").json()["detail"]["code"] == "bad_type"
        assert up(b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_BYTES).json()["detail"]["code"] == "too_big"
        assert up(PNG, h=B).status_code == 403
        assert up(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).json()["detail"]["code"] == "bad_type"  # right magic, not an image
        first = up(PNG).json()
        assert len(first) == 1 and first[0]["content_type"] == "image/png"
        for data in (_gps_photo(), WEBP, PNG, JPG):
            assert up(data, "foto.bin").status_code == 201
        r = up(PNG)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many"

        images = client.get(base, headers=A).json()
        assert [i["content_type"] for i in images] == ["image/png", "image/jpeg", "image/webp", "image/png", "image/jpeg"]
        detail = client.get(f"/products/{product['id']}", headers=A).json()
        assert detail["image_id"] == images[0]["id"] and [i["id"] for i in detail["images"]] == [i["id"] for i in images]
        listed = client.get("/products", params={"q": f"foto {tag}"}, headers=A).json()["items"][0]
        assert listed["image_id"] == images[0]["id"]

        # The file comes back as it was uploaded, cacheable
        f = client.get(f"{base}/{images[1]['id']}", headers=A)
        assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg" and "immutable" in f.headers["cache-control"]
        assert dict(Image.open(io.BytesIO(_gps_photo())).getexif())  # the upload had EXIF with GPS...
        stored = Image.open(io.BytesIO(f.content))
        assert stored.size == (40, 30) and not dict(stored.getexif()) and "exif" not in stored.info  # ...the stored file has none
        assert client.get(f"{base}/{product['id']}", headers=A).status_code == 404  # not an image of this product

        # Main image = first in the order; the order must list every image once
        ids = [i["id"] for i in images]
        assert client.put(f"{base}/order", json={"image_ids": ids[1:]}, headers=A).status_code == 422
        reordered = client.put(f"{base}/order", json={"image_ids": [ids[2], *ids[:2], *ids[3:]]}, headers=A).json()
        assert reordered[0]["id"] == ids[2] and client.get(f"/products/{product['id']}", headers=A).json()["image_id"] == ids[2]

        # Delete: row and file go; then there is room again
        left = client.delete(f"{base}/{ids[2]}", headers=A).json()
        assert len(left) == 4 and client.get(f"{base}/{ids[2]}", headers=A).status_code == 404
        assert up(PNG).status_code == 201
    finally:
        for i in client.get(base, headers=A).json():
            client.delete(f"{base}/{i['id']}", headers=A)
        client.delete(f"/products/{product['id']}", headers=A)
