"""
LAGGAM IPHOTOO Windows folder uploader
Watches Nikon Wireless Transmitter Utility's destination folder and uploads
completed JPG/PNG/WEBP files to one event gallery.
"""
import hashlib
import json
import mimetypes
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.json"
STATE_FILE_TEMPLATE = "uploaded_state_{event_id}.json"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
STABILITY_PASSES = 2
REQUEST_TIMEOUT = (15, 180)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as exc:
        print(f"Cannot read {path.name}: {exc}")
        return default


def save_json(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temp.replace(path)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    config = load_json(CONFIG_FILE, {})
    required = ("base_url", "event_id", "admin_token", "watch_folder")
    missing = [key for key in required if not str(config.get(key, "")).strip()]
    if missing:
        print("config.json is incomplete. Missing: " + ", ".join(missing))
        print("Copy config.example.json to config.json and fill in every field.")
        input("Press Enter to exit...")
        return 2

    base_url = str(config["base_url"]).rstrip("/")
    event_id = str(config["event_id"]).strip()
    token = str(config["admin_token"]).strip()
    watch_folder = Path(str(config["watch_folder"])).expanduser()
    poll_seconds = max(2, int(config.get("poll_seconds", 4)))

    if not watch_folder.is_dir():
        print(f"Folder not found: {watch_folder}")
        print("Check the exact Nikon transfer folder path in config.json.")
        input("Press Enter to exit...")
        return 2

    endpoint = f"{base_url}/api/events/{event_id}/upload"
    headers = {"X-Admin-Token": token}
    session = requests.Session()
    state_file = HERE / STATE_FILE_TEMPLATE.format(event_id=event_id)
    state = load_json(state_file, {})
    stable = {}

    print("=" * 66)
    print("LAGGAM IPHOTOO — Nikon folder auto uploader")
    print(f"Event code : {event_id}")
    print(f"Watch folder: {watch_folder}")
    print(f"Upload API : {endpoint}")
    print("Keep this window open. New completed photos upload automatically.")
    print(f"Upload checkpoint: {state_file.name}")
    print("Original photos remain in your Nikon transfer folder and memory card.")
    print("=" * 66)

    while True:
        try:
            for path in watch_folder.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                try:
                    stat = path.stat()
                    stamp = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    continue

                previous = stable.get(str(path))
                if previous and previous[0] == stamp:
                    passes = previous[1] + 1
                else:
                    passes = 0
                stable[str(path)] = (stamp, passes)
                if passes < STABILITY_PASSES or stat.st_size == 0:
                    continue

                try:
                    digest = file_digest(path)
                except (PermissionError, OSError):
                    continue
                if digest in state:
                    continue

                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                try:
                    with path.open("rb") as photo:
                        response = session.post(
                            endpoint,
                            headers=headers,
                            files={"file": (path.name, photo, content_type)},
                            timeout=REQUEST_TIMEOUT,
                        )
                    if response.status_code in (200, 201):
                        result = response.json()
                        face = result.get("face_index", {})
                        state[digest] = {
                            "name": path.name,
                            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "face_indexed": bool(face.get("indexed")),
                            "faces": int(face.get("faces", 0)),
                        }
                        save_json(state_file, state)
                        print(f"[UPLOADED + FACE INDEXED: {face.get('faces', 0)} faces] {path.name}" if face.get("indexed")
                              else f"[UPLOADED; AI NOT INDEXED] {path.name} — {face.get('reason', 'Check that local face models are installed and the app can load them')}")
                    elif response.status_code == 403:
                        print("[ERROR] Admin token rejected. Download a fresh uploader config from event admin.")
                        time.sleep(15)
                    else:
                        print(f"[RETRY] {path.name}: HTTP {response.status_code} — {response.text[:220]}")
                except requests.RequestException as exc:
                    print(f"[NETWORK] {path.name}: {exc}. Will retry.")
            time.sleep(poll_seconds)
        except KeyboardInterrupt:
            print("\nUploader stopped. Uploaded files are recorded in the event-specific checkpoint file.")
            return 0
        except Exception as exc:
            print(f"[WARNING] {exc}. Retrying in {poll_seconds} seconds.")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    sys.exit(main())
