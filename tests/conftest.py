from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    for module_name in [
        "app",
        "settings",
        "logging_config",
    ]:
        sys.modules.pop(module_name, None)

    spec = importlib.util.spec_from_file_location("app", PROJECT_ROOT / "app.py")
    assert spec and spec.loader
    app_module = importlib.util.module_from_spec(spec)
    sys.modules["app"] = app_module
    spec.loader.exec_module(app_module)
    with TestClient(app_module.app) as client:
        yield client
