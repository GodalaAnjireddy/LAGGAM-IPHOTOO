"""Laptop-hosted LAGGAM IPHOTOO event gallery.

The app runs on the photographer's Windows laptop. Images stay in the selected
camera transfer folder; only SQLite face vectors and event metadata are stored
under the local application data directory.
"""
import hashlib
import io
import mimetypes
import os
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

import qrcode
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

import local_db
from local_face_engine import find_matches, get_engine

ROOT = Path(__file__).resolve().parent
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
SCAN_INTERVAL = float(os.getenv("PHOTOO_SCAN_INTERVAL", "4"))
FACE_THRESHOLD = float(os.getenv("PHOTOO_FACE_THRESHOLD", "0.363"))
MAX_SELFIE_BYTES = 8 * 1024 * 1024

app = FastAPI(title="LAGGAM IPHOTOO — Laptop Event Host")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

_STABLE_FILES = {}
_PROCESSING = set()
_FORCE_SCAN = set()
_SCAN_LOCK = threading.Lock()
_WATCHER_STOP = threading.Event()
_WATCHER_THREAD = None


def owner_pin() -> str:
    path = local_db.DATA_HOME / "studio_pin.txt"
    if not path.exists():
        pin = secrets.token_urlsafe(9)
        path.write_text(pin + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip()


def require_owner(supplied: Optional[str]):
    expected = owner_pin()
    if not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, "Enter the Studio PIN shown in the LAGGAM IPHOTOO server window.")


def require_admin(event_id: str, supplied: Optional[str]):
    if not local_db.verify_admin(event_id, supplied or ""):
        raise HTTPException(403, "Private event admin link is invalid. Reopen the saved Admin link.")


def public_event_url(event_id: str) -> str:
    public_base = local_db.get_setting("public_base_url", "").rstrip("/")
    if not public_base:
        raise HTTPException(503, "Public event link is not ready. Start the Cloudflare Quick Tunnel first.")
    return public_base + "/event/" + event_id


def safe_event(event_id: str):
    if not event_id or len(event_id) > 32 or not all(char in "0123456789ABCDEFabcdef-" for char in event_id):
        raise HTTPException(404, "Event not found")
    result = local_db.get_event(event_id)
    if not result:
        raise HTTPException(404, "Event not found")
    return result


def public_event_summary(event):
    return {
        "id": event["event_id"],
        "name": event["name"],
        "event_type": event["event_type"],
        "date": event["event_date"],
        "venue": event["venue"],
        "created_at": event["created_at"],
        "photo_count": event.get("photo_count", 0),
    }


def process_photo(event, file_path: Path):
    event_id = event["event_id"]
    try:
        stat = file_path.stat()
        if not file_path.is_file() or file_path.suffix.lower() not in IMAGE_EXTS:
            return
        try:
            with Image.open(file_path) as image:
                image.verify()
        except Exception:
            return
        embeddings = []
        status = "photos_only"
        error = ""
        if event["face_search_enabled"]:
            try:
                engine = get_engine()
                embeddings = engine.embeddings_from_file(str(file_path))
                status = "indexed"
            except Exception as exc:
                status = "ai_error"
                error = str(exc)[:500]
        try:
            relative_path = str(file_path.relative_to(Path(event["folder_path"])))
        except ValueError:
            relative_path = file_path.name
        photo_id = uuid.uuid4().hex
        local_db.save_photo_record(
            event_id=event_id,
            photo_id=photo_id,
            path=str(file_path.resolve()),
            file_name=file_path.name,
            relative_path=relative_path,
            size=stat.st_size,
            modified_ns=stat.st_mtime_ns,
            status=status,
            embeddings=[vector.astype("float32").tobytes() for vector in embeddings],
            error_message=error,
        )
        if status == "ai_error":
            print("[FACE AI ERROR] " + file_path.name + ": " + error)
        else:
            print("[INDEXED] " + file_path.name + " — " + str(len(embeddings)) + " faces")
    except (PermissionError, FileNotFoundError):
        return
    except Exception as exc:
        print("[PHOTO PROCESS ERROR] " + file_path.name + ": " + str(exc))


def scan_event_folder(event, force: bool = False):
    folder_text = event.get("folder_path", "")
    if not folder_text:
        return
    folder = Path(folder_text)
    if not folder.is_dir():
        return
    try:
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                stat = path.stat()
            except (PermissionError, FileNotFoundError):
                continue
            absolute = str(path.resolve())
            key = (event["event_id"], absolute)
            if not local_db.photo_needs_processing(event["event_id"], absolute, stat.st_size, stat.st_mtime_ns):
                continue
            if force:
                stable = True
            else:
                previous = _STABLE_FILES.get(key)
                stamp = (stat.st_size, stat.st_mtime_ns)
                if previous and previous[0] == stamp:
                    count = previous[1] + 1
                else:
                    count = 0
                _STABLE_FILES[key] = (stamp, count)
                stable = count >= 1 and (time.time() - stat.st_mtime) >= 1
            if not stable:
                continue
            with _SCAN_LOCK:
                if key in _PROCESSING:
                    continue
                _PROCESSING.add(key)
            try:
                process_photo(event, path)
            finally:
                with _SCAN_LOCK:
                    _PROCESSING.discard(key)
    except PermissionError:
        print("[FOLDER ACCESS] Windows denied access to " + str(folder))


def watcher_loop():
    print("[WATCHER] Folder monitor is running. New completed camera JPEGs will be detected.")
    while not _WATCHER_STOP.wait(SCAN_INTERVAL):
        try:
            for event in local_db.list_events():
                if event.get("folder_path"):
                    force = event["event_id"] in _FORCE_SCAN
                    scan_event_folder(event, force=force)
                    _FORCE_SCAN.discard(event["event_id"])
        except Exception as exc:
            print("[WATCHER WARNING] " + str(exc))


def start_watcher():
    global _WATCHER_THREAD
    if _WATCHER_THREAD and _WATCHER_THREAD.is_alive():
        return
    _WATCHER_STOP.clear()
    _WATCHER_THREAD = threading.Thread(target=watcher_loop, name="photo-folder-watcher", daemon=True)
    _WATCHER_THREAD.start()


@app.on_event("startup")
def startup():
    local_db.init_db()
    if os.getenv("PHOTOO_DISABLE_WATCHER", "0") != "1":
        start_watcher()


@app.on_event("shutdown")
def shutdown():
    _WATCHER_STOP.set()


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.post("/api/admin/verify")
def verify_owner(x_owner_pin: str = Header(default="")):
    require_owner(x_owner_pin)
    return {"ok": True}


@app.get("/api/events")
def events(x_owner_pin: str = Header(default="")):
    require_owner(x_owner_pin)
    return [public_event_summary(event) for event in local_db.list_events()]


@app.post("/api/events")
def create_event(
    name: str = Form(...),
    event_type: str = Form("Wedding"),
    date: str = Form(""),
    venue: str = Form(""),
    x_owner_pin: str = Header(default=""),
):
    require_owner(x_owner_pin)
    name = name.strip()
    if not name:
        raise HTTPException(400, "Enter an event name.")
    allowed = {"Wedding", "Birthday", "Saree Function", "Engagement", "Reception", "Anniversary", "Other Event"}
    if event_type not in allowed:
        raise HTTPException(400, "Select a valid event type.")
    event, token = local_db.create_event(name, event_type, date.strip(), venue.strip())
    event_id = event["event_id"]
    public_base = local_db.get_setting("public_base_url", "").rstrip("/")
    guest_url = (public_base + "/event/" + event_id) if public_base else ("/event/" + event_id)
    admin_url = "/admin/" + event_id + "?key=" + token
    return {
        "event": public_event_summary(event),
        "guest_url": guest_url,
        "admin_url": admin_url,
        "qr_url": "/api/events/" + event_id + "/qr",
    }


@app.get("/event/{event_id}", response_class=HTMLResponse)
def guest(event_id: str):
    event = safe_event(event_id)
    page = (ROOT / "static" / "guest.html").read_text(encoding="utf-8")
    return page.replace("__EVENT__", __import__("json").dumps({
        "name": event["name"], "event_type": event["event_type"],
        "date": event["event_date"], "venue": event["venue"]
    }, ensure_ascii=False).replace("</", "<\\/")).replace("__ID__", event_id)


@app.get("/admin/{event_id}", response_class=HTMLResponse)
def admin(event_id: str, key: str = ""):
    event = safe_event(event_id)
    require_admin(event_id, key)
    page = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")
    safe_data = __import__("json").dumps({
        "name": event["name"], "event_type": event["event_type"],
        "date": event["event_date"], "venue": event["venue"],
        "folder_path": event["folder_path"], "face_search_enabled": bool(event["face_search_enabled"])
    }, ensure_ascii=False).replace("</", "<\\/")
    return page.replace("__EVENT__", safe_data).replace("__ID__", event_id).replace("__ADMIN_TOKEN__", key)


@app.get("/api/events/{event_id}/qr")
def qr(event_id: str):
    safe_event(event_id)
    url = public_event_url(event_id)
    image = qrcode.make(url)
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")


@app.post("/api/events/{event_id}/watch-folder")
def watch_folder(
    event_id: str,
    folder: str = Form(...),
    face_enabled: bool = Form(False),
    x_admin_token: str = Header(default=""),
):
    require_admin(event_id, x_admin_token)
    path = Path(folder.strip().strip('"')).expanduser()
    try:
        path = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise HTTPException(400, "That folder does not exist. Enter the exact Windows folder path.")
    if not path.is_dir():
        raise HTTPException(400, "Select a folder, not a file.")
    if path == Path(path.anchor) or path == Path.home():
        raise HTTPException(400, "Choose a dedicated event folder, not a drive root or your whole user folder.")
    event = local_db.set_event_folder(event_id, str(path), face_enabled)
    _FORCE_SCAN.add(event_id)
    return {
        "ok": True,
        "folder_path": event["folder_path"],
        "face_search_enabled": bool(event["face_search_enabled"]),
        "message": "Folder connected. New photos will be watched automatically.",
    }


@app.post("/api/events/{event_id}/rescan")
def rescan(event_id: str, x_admin_token: str = Header(default="")):
    require_admin(event_id, x_admin_token)
    event = safe_event(event_id)
    if not event.get("folder_path"):
        raise HTTPException(400, "Connect the camera transfer folder first.")
    _FORCE_SCAN.add(event_id)
    return {"ok": True, "message": "Folder rescan queued. New or changed photos will appear as the scan completes."}


@app.get("/api/events/{event_id}/status")
def event_status(event_id: str, x_admin_token: str = Header(default="")):
    require_admin(event_id, x_admin_token)
    event = safe_event(event_id)
    counts = local_db.photo_stats(event_id)
    return {
        "event_id": event_id,
        "folder_path": event["folder_path"],
        "face_search_enabled": bool(event["face_search_enabled"]),
        "public_url": local_db.get_setting("public_base_url", ""),
        "counts": counts,
        "watcher_running": bool(_WATCHER_THREAD and _WATCHER_THREAD.is_alive()),
    }


@app.get("/api/events/{event_id}/photos")
def list_photos(event_id: str, x_admin_token: str = Header(default="")):
    require_admin(event_id, x_admin_token)
    photos = []
    for record in local_db.list_photos(event_id):
        if Path(record["photo_id"] if False else "x").exists():
            pass
        photos.append({
            "id": record["photo_id"],
            "name": record["relative_path"] or record["file_name"],
            "file_name": record["file_name"],
            "url": f"/api/events/{event_id}/photos/{record['photo_id']}",
            "status": record["index_status"],
            "faces": record["face_count"],
            "error": record["error_message"],
        })
    return photos


@app.get("/api/events/{event_id}/photos/{photo_id}")
def get_photo(event_id: str, photo_id: str):
    safe_event(event_id)
    record = local_db.get_photo_record(event_id, photo_id)
    if not record:
        raise HTTPException(404, "Photo is not in this event gallery.")
    path = Path(record["file_path"])
    if not path.is_file():
        raise HTTPException(404, "The original photo is no longer in the watched folder.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.post("/api/events/{event_id}/face-search")
async def face_search(
    event_id: str,
    selfie: UploadFile = File(...),
    consent: bool = Form(False),
):
    event = safe_event(event_id)
    if not event["face_search_enabled"]:
        raise HTTPException(409, "The event organiser has not enabled face matching yet.")
    if not consent:
        raise HTTPException(400, "Please agree to the face-search privacy notice before searching.")
    raw = await selfie.read(MAX_SELFIE_BYTES + 1)
    if len(raw) > MAX_SELFIE_BYTES:
        raise HTTPException(413, "Selfie must be smaller than 8 MB.")
    try:
        engine = get_engine()
        query_vectors = engine.embeddings_from_bytes(raw)
    except Exception as exc:
        raise HTTPException(503, "Local face AI is not ready: " + str(exc)[:240])
    if not query_vectors:
        return {"matches": [], "message": "No clear face was detected. Try a front-facing selfie in good light."}
    vectors = local_db.face_vectors(event_id)
    if not vectors:
        return {"matches": [], "message": "Event photos are still being indexed. Please try again shortly."}
    best_by_photo = {}
    for query_vector in query_vectors:
        for match in find_matches(query_vector, vectors, FACE_THRESHOLD):
            pid = match["photo_id"]
            if pid not in best_by_photo or match["score"] > best_by_photo[pid]["score"]:
                best_by_photo[pid] = match
    matches = sorted(best_by_photo.values(), key=lambda item: item["score"], reverse=True)
    result = [{
        "name": item["name"],
        "url": f"/api/events/{event_id}/photos/{item['photo_id']}",
        "score": round(item["score"], 3),
    } for item in matches[:150]]
    return {
        "matches": result,
        "message": f"{len(result)} matching photos found." if result else "No matching photos found. Try another clear selfie.",
    }


@app.delete("/api/events/{event_id}")
def remove_event(
    event_id: str,
    delete_source_photos: bool = False,
    x_admin_token: str = Header(default=""),
):
    require_admin(event_id, x_admin_token)
    event = safe_event(event_id)
    removed = 0
    if delete_source_photos and event.get("folder_path"):
        folder = Path(event["folder_path"])
        if not folder.is_dir() or folder == Path(folder.anchor) or folder == Path.home():
            raise HTTPException(400, "The saved source folder is no longer safe to delete.")
        for image in folder.rglob("*"):
            if image.is_file() and image.suffix.lower() in IMAGE_EXTS:
                try:
                    image.unlink()
                    removed += 1
                except OSError:
                    pass
    local_db.delete_event(event_id)
    return {
        "ok": True,
        "deleted_event": event_id,
        "source_photos_deleted": removed,
        "message": "Event records and face vectors deleted. Original files were " +
                   ("also deleted from the selected source folder." if delete_source_photos else "left untouched in the source folder."),
    }


@app.get("/api/system/status")
def system_status():
    return {
        "ok": True,
        "service": "LAGGAM IPHOTOO laptop host",
        "public_url": local_db.get_setting("public_base_url", ""),
        "watcher_running": bool(_WATCHER_THREAD and _WATCHER_THREAD.is_alive()),
        "data_directory": str(local_db.DATA_HOME),
        "face_model_downloaded": (local_db.DATA_HOME / "models" / "face_recognition_sface_2021dec.onnx").is_file(),
    }


@app.get("/health")
def health():
    return {"ok": True, "service": "LAGGAM IPHOTOO laptop host"}


@app.get("/robots.txt")
def robots():
    return HTMLResponse("User-agent: *\nDisallow: /admin/\n", media_type="text/plain")
