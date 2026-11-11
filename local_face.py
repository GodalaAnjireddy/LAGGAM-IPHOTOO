"""
Fast free on-device face matching for LAGGAM IPHOTOO.

YuNet detects faces and SFace creates 128-value embeddings. Embeddings are
stored as compact float32 BLOBs in SQLite, with a one-time migration from the
older face_index.json format. No cloud API or paid service is used.
"""
import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parent
MODEL_DIR = Path(os.getenv("PHOTOO_MODEL_DIR", str(ROOT / "models"))).resolve()
YUNET_PATH = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_PATH = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
MODEL_URLS = {
    YUNET_PATH: "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    SFACE_PATH: "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}

MODEL_LOCK = Lock()
ENGINE_LOCK = Lock()
INFERENCE_LOCK = Lock()
DB_LOCK = Lock()
_ENGINE = None
COSINE_THRESHOLD = float(os.getenv("FACE_COSINE_THRESHOLD", "0.363"))
PHOTO_MAX_SIDE = int(os.getenv("FACE_PHOTO_MAX_SIDE", "1600"))
SELFIE_MAX_SIDE = int(os.getenv("FACE_SELFIE_MAX_SIDE", "1100"))


def _download_model(path: Path, url: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 50_000:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "LAGGAM-IPHOTOO/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    if len(data) < 50_000 or data.startswith(b"version https://git-lfs.github.com"):
        raise RuntimeError(f"Could not download the full face model: {path.name}")
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def ensure_models():
    with MODEL_LOCK:
        for path, url in MODEL_URLS.items():
            _download_model(path, url)
    return {"yunet": str(YUNET_PATH), "sface": str(SFACE_PATH)}


def _engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        import cv2
        ensure_models()
        cv2.setUseOptimized(True)
        try:
            cv2.setNumThreads(max(1, int(os.getenv("PHOTOO_OPENCV_THREADS", "2"))))
        except Exception:
            pass
        detector = cv2.FaceDetectorYN_create(
            str(YUNET_PATH), "", (320, 320),
            score_threshold=0.85, nms_threshold=0.30, top_k=3000
        )
        recognizer = cv2.FaceRecognizerSF_create(str(SFACE_PATH), "")
        _ENGINE = (cv2, detector, recognizer)
        return _ENGINE


def _image(raw: bytes, max_side: int):
    import numpy as np
    cv2, detector, recognizer = _engine()
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The image file could not be decoded.")
    height, width = image.shape[:2]
    if max(height, width) > max_side:
        scale = max_side / float(max(height, width))
        image = cv2.resize(
            image,
            (max(1, int(width * scale)), max(1, int(height * scale))),
            interpolation=cv2.INTER_AREA,
        )
        height, width = image.shape[:2]

    # YuNet's detector object is mutable (input size), so serialize just inference.
    with INFERENCE_LOCK:
        detector.setInputSize((width, height))
        _, faces = detector.detect(image)
        vectors = []
        if faces is not None:
            for face in faces:
                aligned = recognizer.alignCrop(image, face)
                feature = recognizer.feature(aligned).reshape(-1).astype("float32")
                norm = float((feature @ feature) ** 0.5)
                if norm > 0:
                    vectors.append(feature / norm)
    return vectors


def _database(event_folder: Path):
    db_path = event_folder / "face_index.sqlite3"
    connection = sqlite3.connect(str(db_path), timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS faces ("
        "filename TEXT NOT NULL, face_no INTEGER NOT NULL, vector BLOB NOT NULL, "
        "PRIMARY KEY(filename, face_no))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    # Import older indexes once so already-uploaded photos remain searchable.
    migrated = connection.execute(
        "SELECT value FROM meta WHERE key='legacy_json_migrated'"
    ).fetchone()
    if not migrated:
        legacy_path = event_folder / "face_index.json"
        if legacy_path.is_file():
            try:
                legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
                face_numbers = {}
                for item in legacy:
                    vector = item.get("vector")
                    filename = item.get("filename")
                    if filename and vector:
                        import numpy as np
                        face_no = face_numbers.get(filename, 0)
                        face_numbers[filename] = face_no + 1
                        blob = np.asarray(vector, dtype=np.float32).tobytes()
                        connection.execute(
                            "INSERT OR REPLACE INTO faces(filename, face_no, vector) VALUES(?,?,?)",
                            (filename, face_no, blob),
                        )
            except Exception as exc:
                connection.close()
                raise RuntimeError(f"Could not migrate the older face index: {exc}") from exc
        connection.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('legacy_json_migrated','yes')"
        )
        connection.commit()
    return connection


def index_photo(event_folder: Path, raw: bytes, filename: str):
    import numpy as np
    vectors = _image(raw, PHOTO_MAX_SIDE)
    with DB_LOCK:
        connection = _database(event_folder)
        try:
            with connection:
                connection.execute("DELETE FROM faces WHERE filename=?", (filename,))
                for face_no, vector in enumerate(vectors):
                    connection.execute(
                        "INSERT INTO faces(filename, face_no, vector) VALUES(?,?,?)",
                        (filename, face_no, np.asarray(vector, dtype=np.float32).tobytes()),
                    )
        finally:
            connection.close()
    return {"indexed": True, "faces": len(vectors), "reason": ""}


def search_photos(event_folder: Path, selfie_bytes: bytes, threshold: float = COSINE_THRESHOLD):
    import numpy as np
    query_vectors = _image(selfie_bytes, SELFIE_MAX_SIDE)
    if not query_vectors:
        return [], "No face was detected. Please use a clear, front-facing selfie in good light."

    with DB_LOCK:
        connection = _database(event_folder)
        try:
            rows = connection.execute("SELECT filename, vector FROM faces").fetchall()
        finally:
            connection.close()

    if not rows:
        return [], "No event photos have been indexed yet. Ask the photographer to upload photos first."

    # A single matrix multiply is substantially faster than Python dot products
    # for every face record, especially when the gallery grows.
    matrix = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
    query_matrix = np.vstack(query_vectors).astype(np.float32, copy=False)
    if matrix.shape[1] != query_matrix.shape[1]:
        raise RuntimeError("Face index model dimensions do not match. Re-index this event's photos.")
    score_matrix = query_matrix @ matrix.T
    max_scores = score_matrix.max(axis=0)

    best_by_photo = {}
    for (filename, _vector), score in zip(rows, max_scores):
        value = float(score)
        if value >= threshold and value > best_by_photo.get(filename, -1.0):
            best_by_photo[filename] = value

    matches = [
        {
            "name": name,
            "url": f"/api/events/{event_folder.name}/photos/{name}",
            "thumbnail_url": f"/api/events/{event_folder.name}/thumbnails/{name}",
            "score": round(score * 100, 1),
        }
        for name, score in sorted(best_by_photo.items(), key=lambda item: item[1], reverse=True)
    ]
    return matches, (
        f"{len(matches)} matching photos found."
        if matches else "No matching photos found. Try another clear selfie."
    )


def clear_event_index(event_folder: Path):
    with DB_LOCK:
        connection = _database(event_folder)
        try:
            with connection:
                connection.execute("DELETE FROM faces")
                # Keep migration marker so the legacy JSON is not re-imported.
                connection.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES('legacy_json_migrated','yes')"
                )
        finally:
            connection.close()
    # Remove legacy JSON after its one-time import/clear to avoid stale data confusion.
    legacy_path = event_folder / "face_index.json"
    try:
        legacy_path.unlink()
    except FileNotFoundError:
        pass
