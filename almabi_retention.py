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
        if not path.is_file() or ".plaintext" in path.parts:
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
        from almabi_file_crypto import append_protected_line

        append_protected_line(journal, json.dumps(record, ensure_ascii=False))
    return {
        "dry_run": not apply,
        "upload_candidates": [str(path) for path in upload_files],
        "log_candidates": [str(path) for path in log_files],
        "deleted": deleted,
    }


def run_scheduled_cleanup(
    *,
    runtime_dir: Path,
    uploads_dir: Path,
    logs_dir: Path,
    upload_retention_days: int,
    log_retention_days: int,
    interval_days: int,
    now: datetime | None = None,
) -> str:
    current = now or datetime.now(UTC)
    state_path = runtime_dir / "retention_state.json"
    last_run = None
    if state_path.is_file():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            last_run = datetime.fromisoformat(str(payload["last_run"]))
        except (OSError, ValueError, KeyError, TypeError):
            last_run = None
    decision = retention_decision(last_run, current, interval_days)
    if decision == "skip":
        return decision
    runtime_dir.mkdir(parents=True, exist_ok=True)
    if decision == "run":
        cleanup(
            uploads_dir=uploads_dir,
            logs_dir=logs_dir,
            upload_retention_days=upload_retention_days,
            log_retention_days=log_retention_days,
            apply=True,
        )
    state_path.write_text(
        json.dumps({"last_run": current.isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )
    return decision


def retention_decision(last_run: datetime | None, now: datetime, interval_days: int) -> str:
    """Первый запуск только запоминает дату. Дальше очистка не чаще чем раз в interval_days."""
    if interval_days < 1:
        return "skip"
    if last_run is None:
        return "record"
    if now - last_run >= timedelta(days=interval_days):
        return "run"
    return "skip"
