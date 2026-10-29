# Integration test: the business logo (Settings): any image in, a clean PNG out, public to read, settings.update to change.
import io

from PIL import Image

from tests.test_calendar import A, B, client


def _image(fmt):
    out = io.BytesIO()
    Image.new("RGB", (900, 300), "navy").save(out, fmt, **({"exif": b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00"} if fmt == "JPEG" else {}))
    return out.getvalue()


def test_logo():
    had = client.get("/settings/logo")
    previous = had.content if had.status_code == 200 else None
    try:
        assert client.put("/settings/logo", files={"file": ("l.jpg", _image("JPEG"), "image/jpeg")}, headers=B).status_code == 403
        assert client.put("/settings/logo", files={"file": ("l.png", b"not an image", "image/png")}, headers=A).status_code == 422
        r = client.put("/settings/logo", files={"file": ("l.jpg", _image("JPEG"), "image/jpeg")}, headers=A)
        assert r.status_code == 200 and r.json()["logo_file"].endswith(".png")
        got = client.get("/settings/logo")  # no sign-in: it's on the public catalog too
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(got.content))
        assert img.format == "PNG" and max(img.size) == 600 and not img.info.get("exif")
        assert client.delete("/settings/logo", headers=A).status_code == 204
        assert client.get("/settings/logo").status_code == 404
    finally:
        if previous:
            client.put("/settings/logo", files={"file": ("l.png", previous, "image/png")}, headers=A)
