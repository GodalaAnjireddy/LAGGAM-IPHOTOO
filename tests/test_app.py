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
    monkeypatch.setattr(application, "index_photo_faces", lambda eid, raw, name: {"indexed": True, "faces": 1, "reason": ""})
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


def test_face_search_requires_consent_and_returns_local_matches(client, monkeypatch):
    import local_face
    monkeypatch.setattr(local_face, "search_photos", lambda folder, raw: ([], "No matching photos found."))
    created = create_event(client)
    event_id = created["event"]["id"]
    photo = jpeg_bytes()
    denied = client.post(
        f"/api/events/{event_id}/face-search",
        files={"selfie": ("selfie.jpg", photo, "image/jpeg")},
        data={"consent": "false"},
    )
    assert denied.status_code == 400
    searched = client.post(
        f"/api/events/{event_id}/face-search",
        files={"selfie": ("selfie.jpg", photo, "image/jpeg")},
        data={"consent": "true"},
    )
    assert searched.status_code == 200
    assert searched.json()["matches"] == []
    assert searched.json()["message"] == "No matching photos found."


def test_legacy_event_folder_remains_accessible(client, tmp_path):
    folder = tmp_path / "ABC12345"
    (folder / "photos").mkdir(parents=True)
    (folder / "event.json").write_text(json.dumps({"id": "ABC12345", "name": "Old event"}), encoding="utf-8")
    assert client.get("/event/ABC12345").status_code == 200
    assert client.get("/admin/ABC12345").status_code == 200

def test_admin_reindex_requires_admin_and_works_with_local_index(client, monkeypatch):
    import local_face
    monkeypatch.setattr(local_face, "clear_event_index", lambda folder: None)
    monkeypatch.setattr(application, "index_photo_faces", lambda eid, raw, name: {"indexed": True, "faces": 1, "reason": ""})
    created = create_event(client)
    event_id = created["event"]["id"]
    denied = client.post(f"/api/events/{event_id}/reindex")
    assert denied.status_code == 403
    allowed = client.post(
        f"/api/events/{event_id}/reindex",
        headers={"X-Admin-Token": created["admin_token"]},
    )
    assert allowed.status_code == 200
    assert allowed.json()["indexed_photos"] == 0
    assert allowed.json()["indexed_faces"] == 0

def test_windows_uploader_source_has_valid_python_syntax():
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "windows-uploader" / "uploader.py"
    ast.parse(source.read_text(encoding="utf-8"))
