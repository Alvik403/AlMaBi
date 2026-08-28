from __future__ import annotations

import argparse
import json

from almabi_retention import cleanup
from settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run or apply AlMaBi retention policy")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete candidates. Without this flag only a report is printed.",
    )
    args = parser.parse_args()
    settings = get_settings()
    report = cleanup(
        uploads_dir=settings.resolved_uploads_dir,
        logs_dir=settings.resolved_logs_dir,
        upload_retention_days=settings.upload_retention_days,
        log_retention_days=settings.log_retention_days,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
