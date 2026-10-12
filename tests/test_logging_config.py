from __future__ import annotations

import logging
import sys

from logging_config import configure_logging
from settings import Settings


def test_configure_logging_falls_back_when_log_dir_not_writable(tmp_path, monkeypatch):
    import logging_config

    logs_dir = tmp_path / "logs"
    settings = Settings(
        logs_dir=logs_dir,
        log_to_files=True,
        auth_enabled=False,
        debug=True,
    )
    monkeypatch.setattr(logging_config, "_logs_dir_writable", lambda _path: False)
    logging_config.configure_logging(settings)

    root = logging.getLogger()
    assert any(isinstance(handler, logging.StreamHandler) for handler in root.handlers)
    assert not any(isinstance(handler, logging.FileHandler) for handler in root.handlers)


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


def test_log_file_is_encrypted_when_data_key_is_set(tmp_path):
    from almabi_file_crypto import configure_data_key, read_protected_text

    logs_dir = tmp_path / "logs"
    settings = Settings(
        logs_dir=logs_dir,
        log_to_files=True,
        auth_enabled=False,
        debug=True,
    )
    key = b"k" * 32
    configure_data_key(key)
    try:
        configure_logging(settings)
        logging.getLogger("test.logging").info("secret-probe")
        body = (logs_dir / "app.log").read_text(encoding="utf-8")
        assert "secret-probe" not in body
        assert "secret-probe" in read_protected_text(logs_dir / "app.log", key)
    finally:
        configure_data_key(None)
