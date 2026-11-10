import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as application


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "DATA", tmp_path)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setattr(application, "rekognition_client", lambda: None)
    return TestClient(application.app)


def create_event(client, event_type="Birthday"):
    response = client.post(
        "/api/events",
        data={"name": "Prabhakar weds Aruna", "event_type": event_type, "date": "2026-11-15", "venue": "Test Hall"},
    )
    assert response.status_code == 200
    return response.json()


def jpeg_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (320, 240), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_home_and_event_categories(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "SriLekha Photography" in response.text
    assert "Prabhakar weds Aruna" in response.text
    assert client.get("/health").json()["ok"] is True


def test_event_is_listed_after_refresh_and_token_is_private(client):
    created = create_event(client)
    event_id = created["event"]["id"]
    assert created["event"]["event_type"] == "Birthday"
    assert created["admin_token"]
    listed = client.get("/api/events").json()
    assert listed[0]["id"] == event_id
    assert "admin_token" not in listed[0]
    assert client.get(f"/event/{event_id}").status_code == 200
    assert client.get(f"/admin/{event_id}").status_code == 403
    assert client.get(f"/admin/{event_id}", params={"key": created["admin_token"]}).status_code == 200


def test_qr_is_public_event_qr(client):
    created = create_event(client)
    response = client.get(created["qr_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_upload_requires_admin_and_lists_gallery(client):
    created = create_event(client)
    event_id = created["event"]["id"]
    photo = jpeg_bytes()
    denied = client.post(f"/api/events/{event_id}/upload", files={"file": ("test.jpg", photo, "image/jpeg")})
    assert denied.status_code == 403
    headers = {"X-Admin-Token": created["admin_token"]}
    uploaded = client.post(
        f"/api/events/{event_id}/upload",
        headers=headers,
        files={"file": ("test.jpg", photo, "image/jpeg")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["ok"] is True
    listed = client.get(f"/api/events/{event_id}/photos", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    public_photo = client.get(listed.json()[0]["url"])
    assert public_photo.status_code == 200
    assert public_photo.content == photo


def test_face_search_requires_consent_and_reports_not_configured(client):
    created = create_event(client)
    event_id = created["event"]["id"]
    photo = jpeg_bytes()
    denied = client.post(
        f"/api/events/{event_id}/face-search",
        files={"selfie": ("selfie.jpg", photo, "image/jpeg")},
        data={"consent": "false"},
    )
    assert denied.status_code == 400
    not_configured = client.post(
        f"/api/events/{event_id}/face-search",
        files={"selfie": ("selfie.jpg", photo, "image/jpeg")},
        data={"consent": "true"},
    )
    assert not_configured.status_code == 503


def test_legacy_event_folder_remains_accessible(client, tmp_path):
    folder = tmp_path / "ABC12345"
    (folder / "photos").mkdir(parents=True)
    (folder / "event.json").write_text(json.dumps({"id": "ABC12345", "name": "Old event"}), encoding="utf-8")
    assert client.get("/event/ABC12345").status_code == 200
    assert client.get("/admin/ABC12345").status_code == 200
