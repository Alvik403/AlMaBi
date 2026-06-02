from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from settings import Settings


@dataclass(frozen=True)
class FileRecord:
    id: int
    original_name: str
    stored_name: str
    sha256: str
    size: int
    mtime: float
    uploaded_at: str
    status: str
    validation_error: str | None
    is_latest: bool
    source: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_name": self.original_name,
            "stored_name": self.stored_name,
            "sha256": self.sha256,
            "size": self.size,
            "mtime": self.mtime,
            "uploaded_at": self.uploaded_at,
            "status": self.status,
            "validation_error": self.validation_error,
            "is_latest": self.is_latest,
            "source": self.source,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database_path = settings.resolved_database_path
        self.uploads_dir = settings.resolved_uploads_dir
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    uploaded_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    validation_error TEXT,
                    is_latest INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'upload'
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_files_latest ON files(is_latest)")

    def row_to_record(self, row: sqlite3.Row | None) -> FileRecord | None:
        if row is None:
            return None
        return FileRecord(
            id=int(row["id"]),
            original_name=str(row["original_name"]),
            stored_name=str(row["stored_name"]),
            sha256=str(row["sha256"]),
            size=int(row["size"]),
            mtime=float(row["mtime"]),
            uploaded_at=str(row["uploaded_at"]),
            status=str(row["status"]),
            validation_error=row["validation_error"],
            is_latest=bool(row["is_latest"]),
            source=str(row["source"]),
        )

    def path_for(self, record: FileRecord) -> Path:
        if record.source == "default":
            return self.settings.default_excel_path
        return self.uploads_dir / record.stored_name

    def ensure_default_file(self, path: Path) -> FileRecord | None:
        if not path.exists():
            return self.get_latest_valid()

        stat = path.stat()
        digest = sha256_file(path)
        uploaded_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM files WHERE source = 'default' AND stored_name = ?",
                (path.name,),
            ).fetchone()
            latest_exists = conn.execute(
                "SELECT 1 FROM files WHERE status = 'valid' AND is_latest = 1"
            ).fetchone()
            is_latest = 0 if latest_exists else 1
            if existing:
                conn.execute(
                    """
                    UPDATE files
                    SET original_name = ?, sha256 = ?, size = ?, mtime = ?, status = 'valid',
                        validation_error = NULL
                    WHERE id = ?
                    """,
                    (path.name, digest, stat.st_size, stat.st_mtime, existing["id"]),
                )
                file_id = int(existing["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO files (
                        original_name, stored_name, sha256, size, mtime, uploaded_at,
                        status, validation_error, is_latest, source
                    ) VALUES (?, ?, ?, ?, ?, ?, 'valid', NULL, ?, 'default')
                    """,
                    (path.name, path.name, digest, stat.st_size, stat.st_mtime, uploaded_at, is_latest),
                )
                file_id = int(cursor.lastrowid)

        return self.get_by_id(file_id)

    def get_by_id(self, file_id: int) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return self.row_to_record(row)

    def get_valid_by_id(self, file_id: int) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE id = ? AND status = 'valid'",
                (file_id,),
            ).fetchone()
        return self.row_to_record(row)

    def get_latest_valid(self) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM files
                WHERE status = 'valid'
                ORDER BY is_latest DESC, uploaded_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        return self.row_to_record(row)

    def list_files(self) -> list[FileRecord]:
        with self.connect() as conn:
            rows: Iterable[sqlite3.Row] = conn.execute(
                "SELECT * FROM files ORDER BY uploaded_at DESC, id DESC"
            ).fetchall()
        return [record for row in rows if (record := self.row_to_record(row)) is not None]

    def add_valid_upload(self, *, original_name: str, stored_name: str, path: Path) -> FileRecord:
        stat = path.stat()
        digest = sha256_file(path)
        uploaded_at = datetime.now(UTC).isoformat()
        with self.connect() as conn:
            conn.execute("UPDATE files SET is_latest = 0 WHERE is_latest = 1")
            cursor = conn.execute(
                """
                INSERT INTO files (
                    original_name, stored_name, sha256, size, mtime, uploaded_at,
                    status, validation_error, is_latest, source
                ) VALUES (?, ?, ?, ?, ?, ?, 'valid', NULL, 1, 'upload')
                """,
                (original_name, stored_name, digest, stat.st_size, stat.st_mtime, uploaded_at),
            )
            file_id = int(cursor.lastrowid)
        record = self.get_by_id(file_id)
        if not record:
            raise RuntimeError("Не удалось зарегистрировать загруженный файл")
        return record
