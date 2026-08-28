from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from settings import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            }:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ErrorOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


def _logs_dir_writable(logs_dir: Path) -> bool:
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        probe = logs_dir / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _attach_file_handler(
    root: logging.Logger,
    *,
    path: Path,
    formatter: logging.Formatter,
    level_filter: logging.Filter | None = None,
) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        return False
    handler.setFormatter(formatter)
    if level_filter is not None:
        handler.addFilter(level_filter)
    root.addHandler(handler)
    return True


def configure_logging(settings: Settings) -> None:
    logs_dir: Path = settings.resolved_logs_dir
    formatter = JsonFormatter()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    if not settings.log_to_files:
        root.warning("File logging disabled (LOG_TO_FILES=false); using stdout only")
        return

    if not _logs_dir_writable(logs_dir):
        root.warning(
            "Log directory is not writable (%s); using stdout only",
            logs_dir,
        )
        return

    if not _attach_file_handler(root, path=logs_dir / "app.log", formatter=formatter):
        root.warning("Could not open %s; using stdout only", logs_dir / "app.log")
        return

    _attach_file_handler(
        root,
        path=logs_dir / "errors.log",
        formatter=formatter,
        level_filter=ErrorOnlyFilter(),
    )
