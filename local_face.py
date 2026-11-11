"""
Free, on-device face matching for LAGGAM IPHOTOO.
Uses the unquantized OpenCV Zoo YuNet + SFace models and stores embeddings
beside each event on the Windows laptop. No AWS account or paid API is used.
"""
import json
import os
import tempfile
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
_ENGINE = None
COSINE_THRESHOLD = float(os.getenv("FACE_COSINE_THRESHOLD", "0.363"))


def _download_model(path: Path, url: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 50_000:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "LAGGAM-IPHOTOO/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    # Git LFS pointer files are small text files; fail clearly rather than loading one as ONNX.
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
        detector = cv2.FaceDetectorYN_create(
            str(YUNET_PATH), "", (320, 320),
            score_threshold=0.85, nms_threshold=0.30, top_k=5000
        )
        recognizer = cv2.FaceRecognizerSF_create(str(SFACE_PATH), "")
        _ENGINE = (cv2, detector, recognizer)
        return _ENGINE


def _image(raw: bytes):
    import numpy as np
    cv2, detector, recognizer = _engine()
    buffer = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The image file could not be decoded.")
    height, width = image.shape[:2]
    # Keep CPU and memory use moderate on older Windows laptops.
    max_side = 1800
    if max(height, width) > max_side:
        scale = max_side / float(max(height, width))
        image = cv2.resize(image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)
        height, width = image.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(image)
    vectors = []
    if faces is not None:
        for face in faces:
            aligned = recognizer.alignCrop(image, face)
            feature = recognizer.feature(aligned).reshape(-1).astype("float32")
            norm = float((feature @ feature) ** 0.5)
            if norm > 0:
                vectors.append((feature / norm).tolist())
    return vectors


def _index_file(event_folder: Path):
    return event_folder / "face_index.json"


def index_photo(event_folder: Path, raw: bytes, filename: str):
    vectors = _image(raw)
    index_path = _index_file(event_folder)
    with MODEL_LOCK:
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = []
        data = [item for item in data if item.get("filename") != filename]
        for vector in vectors:
            data.append({"filename": filename, "vector": vector})
        temp = index_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data), encoding="utf-8")
        temp.replace(index_path)
    return {"indexed": True, "faces": len(vectors), "reason": ""}


def search_photos(event_folder: Path, selfie_bytes: bytes, threshold: float = COSINE_THRESHOLD):
    query_vectors = _image(selfie_bytes)
    if not query_vectors:
        return [], "No face was detected. Please use a clear, front-facing selfie in good light."
    try:
        indexed = json.loads(_index_file(event_folder).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "No event photos have been indexed yet. Ask the photographer to upload photos first."
    best = {}
    import numpy as np
    for item in indexed:
        filename = item.get("filename")
        vector = item.get("vector")
        if not filename or not vector:
            continue
        candidate = np.asarray(vector, dtype=np.float32)
        similarity = max(float(np.dot(query, candidate)) for query in query_vectors)
        if similarity >= threshold and similarity > best.get(filename, -1):
            best[filename] = similarity
    matches = [
        {"name": name, "url": f"/api/events/{event_folder.name}/photos/{name}", "score": round(score * 100, 1)}
        for name, score in sorted(best.items(), key=lambda pair: pair[1], reverse=True)
    ]
    return matches, (f"{len(matches)} matching photos found." if matches else "No matching photos found. Try another clear selfie.")


def clear_event_index(event_folder: Path):
    try:
        _index_file(event_folder).unlink()
    except FileNotFoundError:
        pass
