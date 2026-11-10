"""SQLite persistence for LAGGAM IPHOTOO laptop-hosted events."""
import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_HOME = Path(os.getenv("PHOTOO_LOCAL_DATA", str(Path.home() / "LAGGAM_IPHOTOO_Data"))).expanduser().resolve()
DATA_HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_HOME / "laggam.sqlite3"


def connect():
    db = sqlite3.connect(str(DB_PATH), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_date TEXT NOT NULL DEFAULT '',
            venue TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            folder_path TEXT NOT NULL DEFAULT '',
            face_search_enabled INTEGER NOT NULL DEFAULT 0,
            admin_token_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS photos (
            photo_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            index_status TEXT NOT NULL DEFAULT 'waiting',
            face_count INTEGER NOT NULL DEFAULT 0,
            last_indexed_at TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            UNIQUE(event_id, file_path)
        );
        CREATE TABLE IF NOT EXISTS face_vectors (
            vector_id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id TEXT NOT NULL REFERENCES photos(photo_id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            face_number INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_photos_event ON photos(event_id);
        CREATE INDEX IF NOT EXISTS idx_vectors_photo ON face_vectors(photo_id);
        """)
        db.commit()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_admin(event_id: str, token: str) -> bool:
    with connect() as db:
        row = db.execute("SELECT admin_token_hash FROM events WHERE event_id=?", (event_id,)).fetchone()
    return bool(row and token and secrets.compare_digest(row["admin_token_hash"], token_hash(token)))


def create_event(name: str, event_type: str, event_date: str, venue: str):
    event_id = secrets.token_hex(4).upper()
    token = secrets.token_urlsafe(36)
    created_at = utc_now()
    with connect() as db:
        db.execute(
            "INSERT INTO events(event_id,name,event_type,event_date,venue,created_at,admin_token_hash) VALUES(?,?,?,?,?,?,?)",
            (event_id, name, event_type, event_date, venue, created_at, token_hash(token)),
        )
        db.commit()
    return get_event(event_id), token


def get_event(event_id: str):
    with connect() as db:
        row = db.execute(
            "SELECT event_id,name,event_type,event_date,venue,created_at,folder_path,face_search_enabled FROM events WHERE event_id=?",
            (event_id,),
        ).fetchone()
    return dict(row) if row else None


def list_events():
    with connect() as db:
        rows = db.execute("""
            SELECT e.event_id,e.name,e.event_type,e.event_date,e.venue,e.created_at,
                   e.folder_path,e.face_search_enabled,COUNT(p.photo_id) AS photo_count,
                   SUM(CASE WHEN p.index_status='indexed' THEN 1 ELSE 0 END) AS indexed_count
            FROM events e LEFT JOIN photos p ON p.event_id=e.event_id
            GROUP BY e.event_id ORDER BY e.created_at DESC
        """).fetchall()
    return [dict(row) for row in rows]


def set_event_folder(event_id: str, folder_path: str, face_enabled: bool):
    with connect() as db:
        db.execute(
            "UPDATE events SET folder_path=?,face_search_enabled=? WHERE event_id=?",
            (folder_path, int(face_enabled), event_id),
        )
        if face_enabled:
            # Re-index any existing photos if AI is enabled for the first time.
            db.execute(
                "UPDATE photos SET index_status='waiting',error_message='' WHERE event_id=? AND index_status!='indexed'",
                (event_id,),
            )
        else:
            db.execute("DELETE FROM face_vectors WHERE photo_id IN (SELECT photo_id FROM photos WHERE event_id=?)", (event_id,))
            db.execute(
                "UPDATE photos SET index_status='photos_only',face_count=0,error_message='' WHERE event_id=?",
                (event_id,),
            )
        db.commit()
    return get_event(event_id)


def event_for_admin(event_id: str):
    return get_event(event_id)


def get_photo_record(event_id: str, photo_id: str):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM photos WHERE event_id=? AND photo_id=?",
            (event_id, photo_id),
        ).fetchone()
    return dict(row) if row else None


def list_photos(event_id: str):
    with connect() as db:
        rows = db.execute(
            "SELECT photo_id,file_name,relative_path,index_status,face_count,error_message FROM photos WHERE event_id=? ORDER BY relative_path",
            (event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def photo_stats(event_id: str):
    with connect() as db:
        row = db.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN index_status='indexed' THEN 1 ELSE 0 END) AS indexed,
                   SUM(CASE WHEN index_status='waiting' THEN 1 ELSE 0 END) AS waiting,
                   SUM(face_count) AS faces
            FROM photos WHERE event_id=?
        """, (event_id,)).fetchone()
    return {key: int(row[key] or 0) for key in ("total", "indexed", "waiting", "faces")}


def photo_needs_processing(event_id: str, path: str, size: int, modified_ns: int):
    with connect() as db:
        row = db.execute(
            "SELECT photo_id,file_size,modified_ns,index_status FROM photos WHERE event_id=? AND file_path=?",
            (event_id, path),
        ).fetchone()
    if row and row["file_size"] == size and row["modified_ns"] == modified_ns and row["index_status"] in ("indexed", "photos_only"):
        return False
    return True


def save_photo_record(event_id: str, photo_id: str, path: str, file_name: str,
                      relative_path: str, size: int, modified_ns: int,
                      status: str, embeddings, error_message: str = ""):
    now = utc_now()
    with connect() as db:
        existing = db.execute(
            "SELECT photo_id FROM photos WHERE event_id=? AND file_path=?",
            (event_id, path),
        ).fetchone()
        if existing:
            photo_id = existing["photo_id"]
            db.execute("DELETE FROM face_vectors WHERE photo_id=?", (photo_id,))
            db.execute("""
                UPDATE photos SET file_name=?,relative_path=?,file_size=?,modified_ns=?,
                index_status=?,face_count=?,last_indexed_at=?,error_message=? WHERE photo_id=?
            """, (file_name, relative_path, size, modified_ns, status, len(embeddings), now, error_message, photo_id))
        else:
            db.execute("""
                INSERT INTO photos(photo_id,event_id,file_path,file_name,relative_path,file_size,modified_ns,
                index_status,face_count,last_indexed_at,error_message)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (photo_id, event_id, path, file_name, relative_path, size, modified_ns,
                  status, len(embeddings), now, error_message))
        for index, embedding in enumerate(embeddings):
            db.execute(
                "INSERT INTO face_vectors(photo_id,embedding,face_number) VALUES(?,?,?)",
                (photo_id, sqlite3.Binary(embedding), index),
            )
        db.commit()
    return photo_id


def pending_or_unindexed(event_id: str):
    with connect() as db:
        rows = db.execute(
            "SELECT file_path,file_size,modified_ns FROM photos WHERE event_id=? AND index_status IN ('waiting','ai_error')",
            (event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def face_vectors(event_id: str):
    with connect() as db:
        rows = db.execute("""
            SELECT p.photo_id,p.file_name,f.embedding
            FROM photos p JOIN face_vectors f ON f.photo_id=p.photo_id
            WHERE p.event_id=? AND p.index_status='indexed'
        """, (event_id,)).fetchall()
    return [dict(row) for row in rows]


def set_setting(key: str, value: str):
    with connect() as db:
        db.execute(
            "INSERT INTO settings(setting_key,setting_value) VALUES(?,?) "
            "ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value",
            (key, value),
        )
        db.commit()


def get_setting(key: str, default: str = ""):
    with connect() as db:
        row = db.execute("SELECT setting_value FROM settings WHERE setting_key=?", (key,)).fetchone()
    return row["setting_value"] if row else default


def delete_event(event_id: str):
    with connect() as db:
        db.execute("DELETE FROM events WHERE event_id=?", (event_id,))
        db.commit()
