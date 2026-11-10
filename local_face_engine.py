"""Local offline face detection and matching using OpenCV YuNet + SFace."""
import io
import os
import threading
import urllib.request
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import local_db

MODEL_DIR = local_db.DATA_HOME / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
YUNET_FILE = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_FILE = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
SFACE_URL = "https://github.com/opencv/opencv_zoo/raw/refs/heads/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"
MAX_IMAGE_SIDE = int(os.getenv("PHOTOO_FACE_MAX_SIDE", "2200"))
MODEL_LOCK = threading.Lock()


def _download_model(url: str, target: Path):
    if target.exists() and target.stat().st_size > 100_000:
        return
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(url, headers={"User-Agent": "LAGGAM-IPHOTOO/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        if temporary.stat().st_size < 100_000:
            raise RuntimeError("The downloaded face model is unexpectedly small.")
        temporary.replace(target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            "Could not download the OpenCV face models. Connect this laptop to the Internet and retry. "
            + str(exc)
        ) from exc


class LocalFaceEngine:
    def __init__(self):
        with MODEL_LOCK:
            _download_model(YUNET_URL, YUNET_FILE)
            _download_model(SFACE_URL, SFACE_FILE)
            self.detector = cv2.FaceDetectorYN.create(
                str(YUNET_FILE), "", (320, 320),
                score_threshold=0.82, nms_threshold=0.3, top_k=5000
            )
            self.recognizer = cv2.FaceRecognizerSF.create(str(SFACE_FILE), "")
        self.lock = threading.Lock()

    @staticmethod
    def _to_bgr(image_bytes: bytes):
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        array = np.asarray(image)
        return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _resize(bgr):
        height, width = bgr.shape[:2]
        longest = max(height, width)
        if longest > MAX_IMAGE_SIDE:
            scale = MAX_IMAGE_SIDE / float(longest)
            bgr = cv2.resize(
                bgr,
                (max(1, int(width * scale)), max(1, int(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        return bgr

    def embeddings_from_bytes(self, image_bytes: bytes):
        bgr = self._resize(self._to_bgr(image_bytes))
        height, width = bgr.shape[:2]
        with self.lock:
            self.detector.setInputSize((width, height))
            _status, faces = self.detector.detect(bgr)
            if faces is None or len(faces) == 0:
                return []
            vectors = []
            for face in faces:
                aligned = self.recognizer.alignCrop(bgr, face)
                feature = self.recognizer.feature(aligned)
                vector = np.asarray(feature, dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(vector))
                if norm > 0:
                    vector = vector / norm
                    vectors.append(vector.astype(np.float32))
        return vectors

    def embeddings_from_file(self, file_path: str):
        path = Path(file_path)
        raw = path.read_bytes()
        return self.embeddings_from_bytes(raw)


_ENGINE = None
_ENGINE_LOCK = threading.Lock()


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = LocalFaceEngine()
    return _ENGINE


def find_matches(query_embedding, stored_vectors, threshold: float = 0.363):
    query = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
    query_norm = float(np.linalg.norm(query))
    if query_norm == 0:
        return []
    query = query / query_norm
    best = {}
    for row in stored_vectors:
        vector = np.frombuffer(row["embedding"], dtype=np.float32)
        if vector.size != query.size:
            continue
        score = float(np.dot(query, vector))
        photo_id = row["photo_id"]
        if score >= threshold and (photo_id not in best or score > best[photo_id]["score"]):
            best[photo_id] = {
                "photo_id": photo_id,
                "name": row["file_name"],
                "score": score,
            }
    return sorted(best.values(), key=lambda item: item["score"], reverse=True)
