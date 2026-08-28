from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def expired_files(root: Path, retention_days: int, *, now: datetime | None = None) -> list[Path]:
    if retention_days < 1 or not root.exists():
        return []
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=retention_days)
    result: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified < cutoff:
            result.append(path)
    return sorted(result)


def cleanup(
    *,
    uploads_dir: Path,
    logs_dir: Path,
    upload_retention_days: int,
    log_retention_days: int,
    apply: bool = False,
) -> dict[str, Any]:
    upload_files = expired_files(uploads_dir, upload_retention_days)
    log_files = [
        path
        for path in expired_files(logs_dir, log_retention_days)
        if path.name != "retention.jsonl"
    ]
    deleted: list[str] = []
    if apply:
        for path in [*upload_files, *log_files]:
            path.unlink(missing_ok=True)
            deleted.append(str(path))
        logs_dir.mkdir(parents=True, exist_ok=True)
        journal = logs_dir / "retention.jsonl"
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event": "retention_cleanup",
            "deleted_count": len(deleted),
            "deleted": deleted,
        }
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "dry_run": not apply,
        "upload_candidates": [str(path) for path in upload_files],
        "log_candidates": [str(path) for path in log_files],
        "deleted": deleted,
    }
