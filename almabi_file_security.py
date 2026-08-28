from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from starlette.requests import Request


_STORED_XLSX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\.xlsx$", re.IGNORECASE)


def resolve_stored_xlsx(base_dir: Path, stored_name: object) -> Path | None:
    """Resolve a server-generated workbook name without allowing directory escape."""
    if not isinstance(stored_name, str) or not _STORED_XLSX_RE.fullmatch(stored_name):
        return None
    base = base_dir.resolve()
    candidate = (base / stored_name).resolve()
    if not candidate.is_relative_to(base):
        return None
    return candidate if candidate.is_file() else None


def user_upload_dir(request: Request, uploads_root: Path, namespace: str) -> Path:
    legacy = uploads_root / namespace
    user_id: Any = request.session.get("auth_user_id")
    if user_id is None:
        legacy.mkdir(parents=True, exist_ok=True)
        return legacy
    safe_user_id = re.sub(r"[^A-Za-z0-9_-]", "", str(user_id))
    if not safe_user_id:
        raise ValueError("Invalid authenticated user identifier")
    scoped = legacy / "users" / safe_user_id
    scoped.mkdir(parents=True, exist_ok=True)
    return scoped


def resolve_user_stored_xlsx(
    request: Request,
    uploads_root: Path,
    namespace: str,
    stored_name: object,
) -> Path | None:
    scoped = user_upload_dir(request, uploads_root, namespace)
    resolved = resolve_stored_xlsx(scoped, stored_name)
    if resolved is not None or scoped == uploads_root / namespace:
        return resolved
    # Additive compatibility path for UUID files created before user isolation.
    return resolve_stored_xlsx(uploads_root / namespace, stored_name)


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def write_limited(source: Any, target: Path, max_bytes: int) -> int:
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Файл превышает лимит {max_bytes} байт")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return total
