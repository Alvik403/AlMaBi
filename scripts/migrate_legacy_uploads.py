from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from almabi_file_security import resolve_stored_xlsx  # noqa: E402
from settings import get_settings  # noqa: E402


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Additively copy pre-auth UUID uploads into one user's isolated storage"
    )
    parser.add_argument("user_id", help="Numeric local user ID from manage_users.py list")
    parser.add_argument("--apply", action="store_true", help="Copy files; default is dry-run")
    args = parser.parse_args()
    if not args.user_id.isdigit():
        raise SystemExit("user_id must be numeric")

    root = get_settings().resolved_uploads_dir
    records = []
    for namespace in ("almabi", "almabi_test_excel"):
        source_dir = root / namespace
        target_dir = source_dir / "users" / args.user_id
        for candidate in sorted(source_dir.glob("*.xlsx")):
            source = resolve_stored_xlsx(source_dir, candidate.name)
            if source is None:
                continue
            target = target_dir / source.name
            record = {
                "namespace": namespace,
                "source": str(source),
                "target": str(target),
                "sha256": checksum(source),
                "status": "planned",
            }
            if args.apply:
                target_dir.mkdir(parents=True, exist_ok=True)
                if target.exists() and checksum(target) != record["sha256"]:
                    raise SystemExit(f"Checksum conflict: {target}")
                if not target.exists():
                    shutil.copy2(source, target)
                if checksum(target) != record["sha256"]:
                    target.unlink(missing_ok=True)
                    raise SystemExit(f"Checksum verification failed: {target}")
                record["status"] = "copied"
            records.append(record)
    print(json.dumps({"dry_run": not args.apply, "files": records}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
