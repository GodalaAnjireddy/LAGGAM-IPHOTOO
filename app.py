import io
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("PHOTOO_DATA", "./data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
FACE_THRESHOLD = float(os.getenv("FACE_THRESHOLD", "85"))

app = FastAPI(title="LAGGAM IPHOTOO")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def safe_event_id(eid: str) -> str:
    if not eid or not all(c in "0123456789ABCDEFabcdef-" for c in eid):
        raise HTTPException(404, "Event not found")
    return eid


def event_dir(eid: str) -> Path:
    folder = (DATA / safe_event_id(eid)).resolve()
    if DATA not in folder.parents or not folder.is_dir():
        raise HTTPException(404, "Event not found")
    return folder


def read_event(eid: str):
    folder = event_dir(eid)
    metadata = folder / "event.json"
    if not metadata.is_file():
        raise HTTPException(404, "Event not found")
    return json.loads(metadata.read_text(encoding="utf-8")), folder


def write_json(path: Path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def require_admin(eid: str, supplied: Optional[str]):
    event, _ = read_event(eid)
    expected = event.get("admin_token", "")
    # Legacy event folders created before admin links were secured remain accessible
    # so existing test events are not locked out during this upgrade.
    if expected and (not supplied or not secrets.compare_digest(expected, supplied)):
        raise HTTPException(403, "Admin token missing or invalid. Open the private admin link created with this event.")
    return event


def rekognition_client():
    if not os.getenv("AWS_ACCESS_KEY_ID") or not os.getenv("AWS_SECRET_ACCESS_KEY"):
        return None
    try:
        import boto3
        return boto3.client("rekognition", region_name=AWS_REGION)
    except Exception:
        return None


def ensure_face_collection(eid: str):
    client = rekognition_client()
    if client is None:
        return None
    collection_id = f"laggam-{eid.lower()}"
    try:
        client.describe_collection(CollectionId=collection_id)
    except client.exceptions.ResourceNotFoundException:
        client.create_collection(CollectionId=collection_id)
    return client


def normalized_jpeg(raw: bytes) -> bytes:
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()


def index_photo_faces(eid: str, raw: bytes, filename: str):
    client = ensure_face_collection(eid)
    if client is None:
        return {"indexed": False, "faces": 0, "reason": "Face search is not configured. Add AWS Rekognition credentials to Render."}
    image_bytes = normalized_jpeg(raw)
    if len(image_bytes) > 5 * 1024 * 1024:
        image = Image.open(io.BytesIO(image_bytes))
        image.thumbnail((2400, 2400))
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        image_bytes = output.getvalue()
    response = client.index_faces(
        CollectionId=f"laggam-{eid.lower()}",
        Image={"Bytes": image_bytes},
        ExternalImageId=filename[:255],
        DetectionAttributes=[],
        MaxFaces=100,
        QualityFilter="AUTO",
    )
    return {"indexed": True, "faces": len(response.get("FaceRecords", [])), "reason": ""}


def list_event_records():
    records = []
    for folder in DATA.iterdir():
        if not folder.is_dir():
            continue
        metadata = folder / "event.json"
        if not metadata.is_file():
            continue
        try:
            event = json.loads(metadata.read_text(encoding="utf-8"))
            photo_dir = folder / "photos"
            event["photo_count"] = sum(1 for item in photo_dir.iterdir() if item.is_file()) if photo_dir.is_dir() else 0
            records.append(event)
        except Exception:
            continue
    return sorted(records, key=lambda item: item.get("created_at", ""), reverse=True)


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/api/events")
def events():
    # Public summaries only. Never expose event admin tokens.
    fields = ("id", "name", "event_type", "date", "venue", "created_at", "photo_count")
    return [{key: event.get(key, "") for key in fields} for event in list_event_records()]


@app.post("/api/events")
def create_event(
    name: str = Form(...),
    event_type: str = Form("Wedding"),
    date: str = Form(""),
    venue: str = Form(""),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Enter an event name.")
    allowed = {"Wedding", "Birthday", "Saree Function", "Engagement", "Reception", "Anniversary", "Other Event"}
    if event_type not in allowed:
        raise HTTPException(400, "Select a valid event type.")
    event_id = uuid.uuid4().hex[:8].upper()
    folder = DATA / event_id
    (folder / "photos").mkdir(parents=True, exist_ok=False)
    token = secrets.token_urlsafe(32)
    event = {
        "id": event_id,
        "name": name,
        "event_type": event_type,
        "date": date,
        "venue": venue.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "admin_token": token,
    }
    write_json(folder / "event.json", event)
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    guest_url = f"{base}/event/{event_id}" if base else f"/event/{event_id}"
    admin_url = f"{base}/admin/{event_id}?key={token}" if base else f"/admin/{event_id}?key={token}"
    public_event = {key: value for key, value in event.items() if key != "admin_token"}
    return {
        "event": public_event,
        "guest_url": guest_url,
        "admin_url": admin_url,
        "admin_token": token,
        "qr_url": f"/api/events/{event_id}/qr",
    }


@app.get("/event/{eid}", response_class=HTMLResponse)
def guest(eid: str):
    event, _ = read_event(eid)
    page = (ROOT / "static" / "guest.html").read_text(encoding="utf-8")
    safe_event = json.dumps({key: value for key, value in event.items() if key != "admin_token"}, ensure_ascii=False).replace("</", "<\\/")
    return page.replace("__EVENT__", safe_event).replace("__ID__", eid)


@app.get("/admin/{eid}", response_class=HTMLResponse)
def admin(eid: str, key: str = ""):
    event, _ = read_event(eid)
    if event.get("admin_token") and (not key or not secrets.compare_digest(event.get("admin_token", ""), key)):
        return HTMLResponse(
            "<h2>Private admin link required</h2><p>Open the private admin link provided when this event was created. Do not share it with guests.</p>",
            status_code=403,
        )
    page = (ROOT / "static" / "admin.html").read_text(encoding="utf-8")
    safe_event = json.dumps({field: value for field, value in event.items() if field != "admin_token"}, ensure_ascii=False).replace("</", "<\\/")
    return page.replace("__EVENT__", safe_event).replace("__ID__", eid).replace("__ADMIN_TOKEN__", key)


@app.get("/api/events/{eid}/qr")
def qr(eid: str):
    read_event(eid)
    import qrcode
    origin = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not origin:
        raise HTTPException(400, "Set PUBLIC_BASE_URL to the deployed HTTPS URL.")
    image = qrcode.make(f"{origin}/event/{eid}")
    output = io.BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return StreamingResponse(output, media_type="image/png")


@app.post("/api/events/{eid}/upload")
async def upload(eid: str, file: UploadFile = File(...), x_admin_token: str = Header(default="")):
    require_admin(eid, x_admin_token)
    _, folder = read_event(eid)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Image exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if Path(file.filename or "").suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(400, "Only JPG, JPEG, PNG and WEBP images are supported.")
    try:
        Image.open(io.BytesIO(raw)).verify()
    except Exception:
        raise HTTPException(400, "The uploaded file is not a valid image.")
    extension = Path(file.filename or ".jpg").suffix.lower()
    filename = f"{uuid.uuid4().hex}{extension}"
    (folder / "photos" / filename).write_bytes(raw)
    face_status = {"indexed": False, "faces": 0, "reason": "Face AI not configured"}
    try:
        face_status = index_photo_faces(eid, raw, filename)
    except Exception as exc:
        face_status = {"indexed": False, "faces": 0, "reason": f"Face indexing failed: {type(exc).__name__}"}
    return {
        "ok": True,
        "name": filename,
        "photo_url": f"/api/events/{eid}/photos/{filename}",
        "face_index": face_status,
    }


@app.get("/api/events/{eid}/photos")
def list_photos(eid: str, x_admin_token: str = Header(default="")):
    require_admin(eid, x_admin_token)
    _, folder = read_event(eid)
    photo_dir = folder / "photos"
    return [{"name": path.name, "url": f"/api/events/{eid}/photos/{path.name}"} for path in sorted(photo_dir.iterdir()) if path.is_file()]


@app.get("/api/events/{eid}/photos/{name}")
def get_photo(eid: str, name: str):
    _, folder = read_event(eid)
    filename = Path(name).name
    photo = folder / "photos" / filename
    if not photo.is_file():
        raise HTTPException(404, "Photo not found.")
    return FileResponse(photo, filename=filename)


@app.post("/api/events/{eid}/face-search")
async def face_search(eid: str, selfie: UploadFile = File(...), consent: bool = Form(False)):
    read_event(eid)
    if not consent:
        raise HTTPException(400, "Please agree to the face-search privacy notice before continuing.")
    raw = await selfie.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "Selfie must be smaller than 8 MB.")
    try:
        image_bytes = normalized_jpeg(raw)
    except Exception:
        raise HTTPException(400, "Please upload a valid selfie.")
    client = rekognition_client()
    if client is None:
        raise HTTPException(503, "Face matching is not configured yet. The event gallery is available, but AI search needs AWS Rekognition setup by the administrator.")
    collection_id = f"laggam-{eid.lower()}"
    try:
        try:
            client.describe_collection(CollectionId=collection_id)
        except client.exceptions.ResourceNotFoundException:
            return {"matches": [], "message": "No event photos have been indexed yet. Ask the photographer to upload photos first."}
        response = client.search_faces_by_image(
            CollectionId=collection_id,
            Image={"Bytes": image_bytes},
            FaceMatchThreshold=FACE_THRESHOLD,
            MaxFaces=100,
            QualityFilter="AUTO",
        )
    except client.exceptions.InvalidParameterException:
        return {"matches": [], "message": "No clear face was detected. Please try a front-facing selfie in good light."}
    except Exception as exc:
        raise HTTPException(502, f"Face search service error: {type(exc).__name__}")
    best = {}
    for item in response.get("FaceMatches", []):
        filename = item.get("Face", {}).get("ExternalImageId")
        if filename:
            similarity = float(item.get("Similarity", 0))
            if filename not in best or similarity > best[filename]:
                best[filename] = similarity
    matches = [
        {"name": filename, "url": f"/api/events/{eid}/photos/{filename}", "score": round(score, 1)}
        for filename, score in sorted(best.items(), key=lambda item: item[1], reverse=True)
    ]
    message = f"{len(matches)} matching photos found." if matches else "No matching photos found. Try another clear selfie."
    return {"matches": matches, "message": message}


@app.get("/api/events/{eid}/uploader-config")
def uploader_config(eid: str, key: str = ""):
    event, _ = read_event(eid)
    if not key or not secrets.compare_digest(event.get("admin_token", ""), key):
        raise HTTPException(403, "Private admin link required.")
    base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    if not base:
        raise HTTPException(400, "PUBLIC_BASE_URL is not configured.")
    return {
        "base_url": base,
        "watch_folder": "",
        "event_id": eid,
        "admin_token": key,
        "poll_seconds": 4,
        "max_file_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "LAGGAM IPHOTOO",
        "face_matching_configured": bool(rekognition_client()),
        "storage_path": str(DATA),
        "note": "Persistent storage must be configured on the host before real events.",
    }


@app.get("/robots.txt")
def robots():
    return HTMLResponse("User-agent: *\nDisallow: /admin/\n", media_type="text/plain")
