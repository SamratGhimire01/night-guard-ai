"""Logo upload + website widget settings (app/services/branding_service.py, routes in business.py / widget.py).

Real HTTP through the app, real Postgres. Covers: upload/serve/replace/delete of the logo, file-type and size limits,
role and tenant boundaries, and the widget settings round trip into the public widget config."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models.business import Business
from app.main import app

client = TestClient(app)

# Smallest valid files of each accepted type (signature is what the server checks).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _register(label: str) -> tuple[str, dict]:
    email = f"{label}-{uuid.uuid4().hex[:10]}@example.com"
    resp = client.post(
        "/api/v1/auth/register",
        json={"business_name": f"{label} Clinic", "timezone": "UTC", "email": email, "password": "correcthorse1"},
    )
    assert resp.status_code == 201, resp.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "correcthorse1"})
    return resp.json()["business_id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture
def owner():
    business_id, headers = _register("brand")
    yield business_id, headers
    with SessionLocal() as db:
        b = db.get(Business, uuid.UUID(business_id))
        if b is not None:
            db.delete(b)
        db.commit()


def _upload(headers, raw, name="logo.png", ctype="image/png"):
    return client.post("/api/v1/business/logo", headers=headers, files={"file": (name, raw, ctype)})


@pytest.mark.parametrize(("raw", "ctype"), [(PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_upload_logo_is_served_publicly_with_its_real_type(owner, raw, ctype):
    business_id, headers = owner
    resp = _upload(headers, raw)
    assert resp.status_code == 200, resp.text
    logo_url = resp.json()["logo_url"]
    assert logo_url.startswith(f"/api/v1/widget/{business_id}/logo?v=")

    served = client.get(logo_url)
    assert served.status_code == 200
    assert served.content == raw
    assert served.headers["content-type"] == ctype
    assert served.headers["x-content-type-options"] == "nosniff"

    # The public widget config hands the same URL to the embedded widget.
    assert client.get(f"/api/v1/widget/{business_id}/config").json()["logo_url"] == logo_url


def test_replacing_the_logo_changes_the_version_so_caches_refresh(owner):
    _, headers = owner
    first = _upload(headers, PNG).json()["logo_url"]
    second = _upload(headers, JPEG, "logo.jpg", "image/jpeg").json()["logo_url"]
    assert first != second


def test_svg_and_other_files_are_rejected_even_when_named_png(owner):
    _, headers = owner
    assert _upload(headers, SVG, "logo.png", "image/png").status_code == 415
    assert _upload(headers, b"GIF89a" + b"\x00" * 20, "logo.gif", "image/gif").status_code == 415


def test_logo_over_one_megabyte_is_rejected(owner):
    _, headers = owner
    assert _upload(headers, PNG + b"\x00" * (1024 * 1024)).status_code == 413


def test_delete_logo_clears_it_everywhere(owner):
    business_id, headers = owner
    url = _upload(headers, PNG).json()["logo_url"]
    resp = client.delete("/api/v1/business/logo", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["logo_url"] is None
    assert client.get(url).status_code == 404
    assert client.get(f"/api/v1/widget/{business_id}/config").json()["logo_url"] is None


def test_logo_upload_requires_login():
    assert client.post("/api/v1/business/logo", files={"file": ("l.png", PNG, "image/png")}).status_code == 401


def test_logo_route_for_a_business_without_a_logo_is_404(owner):
    business_id, _ = owner
    assert client.get(f"/api/v1/widget/{business_id}/logo").status_code == 404


def test_widget_settings_default_to_a_complete_widget(owner):
    business_id, headers = owner
    settings = client.get("/api/v1/business/widget-settings", headers=headers).json()
    assert settings["launcher_icon"] == "chat"
    assert settings["position"] == "right"
    assert settings["suggested_questions"] == []
    config = client.get(f"/api/v1/widget/{business_id}/config").json()
    assert config["name"] == "brand Clinic"
    assert config["show_branding"] is True


def test_widget_settings_round_trip_into_the_public_config(owner):
    business_id, headers = owner
    payload = {
        "display_name": "Smile Assistant",
        "subtitle": "Replies in seconds",
        "welcome_message": "Namaste! How can we help?",
        "suggested_questions": ["What are your hours?", "  ", "How much is a cleaning?"],
        "input_placeholder": "Ask anything",
        "launcher_icon": "sparkles",
        "launcher_label": "Chat with us",
        "position": "left",
        "theme": "dark",
        "show_popup": False,
        "popup_delay_seconds": 10,
        "show_branding": False,
    }
    resp = client.put("/api/v1/business/widget-settings", headers=headers, json=payload)
    assert resp.status_code == 200, resp.text
    # Blank suggestions are dropped.
    assert resp.json()["suggested_questions"] == ["What are your hours?", "How much is a cleaning?"]

    config = client.get(f"/api/v1/widget/{business_id}/config").json()
    for key in ("display_name", "welcome_message", "launcher_icon", "position", "theme", "show_branding"):
        assert config[key] == payload[key]


@pytest.mark.parametrize(
    "bad",
    [
        {"launcher_icon": "rocket"},
        {"position": "top"},
        {"popup_delay_seconds": 999},
        {"suggested_questions": ["a", "b", "c", "d", "e"]},
        {"welcome_message": "x" * 401},
    ],
)
def test_widget_settings_reject_invalid_values(owner, bad):
    _, headers = owner
    assert client.put("/api/v1/business/widget-settings", headers=headers, json=bad).status_code == 422


def test_widget_settings_never_leak_between_businesses(owner):
    business_a, headers_a = owner
    business_b, headers_b = _register("other")
    try:
        client.put("/api/v1/business/widget-settings", headers=headers_a, json={"display_name": "A only"})
        _upload(headers_a, PNG)
        assert client.get(f"/api/v1/widget/{business_b}/config").json()["display_name"] == ""
        assert client.get(f"/api/v1/widget/{business_b}/logo").status_code == 404
        assert client.get("/api/v1/business/widget-settings", headers=headers_b).json()["display_name"] == ""
    finally:
        with SessionLocal() as db:
            db.delete(db.get(Business, uuid.UUID(business_b)))
            db.commit()
