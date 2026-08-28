from __future__ import annotations

import logging
import sys

from logging_config import configure_logging
from settings import Settings


def test_configure_logging_falls_back_when_log_dir_not_writable(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    settings = Settings(
        logs_dir=logs_dir,
        log_to_files=True,
        auth_enabled=False,
        debug=True,
    )
    monkeypatch.setattr("logging_config._logs_dir_writable", lambda _path: False)
    configure_logging(settings)

    root = logging.getLogger()
    assert any(isinstance(handler, logging.StreamHandler) for handler in root.handlers)
    assert not any(type(handler).__name__ == "FileHandler" for handler in root.handlers)


def test_configure_logging_writes_files_when_dir_writable(tmp_path):
    logs_dir = tmp_path / "logs"
    settings = Settings(
        logs_dir=logs_dir,
        log_to_files=True,
        auth_enabled=False,
        debug=True,
    )
    configure_logging(settings)
    logging.getLogger("test.logging").info("probe")
    for handler in logging.getLogger().handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    assert (logs_dir / "app.log").is_file()
    assert "probe" in (logs_dir / "app.log").read_text(encoding="utf-8")
