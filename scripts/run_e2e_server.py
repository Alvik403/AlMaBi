from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

runtime = PROJECT_ROOT / "runtime" / "e2e"
os.environ.update(
    {
        "DEBUG": "true",
        "AUTH_ENABLED": "true",
        "SESSION_SECRET": "e2e-session-secret-with-at-least-32-characters",
        "SESSION_HTTPS_ONLY": "false",
        "RUNTIME_DIR": str(runtime),
        "UPLOADS_DIR": str(runtime / "uploads"),
        "LOGS_DIR": str(runtime / "logs"),
        "AUTH_DB": str(runtime / "auth.sqlite3"),
        "ALLOWED_HOSTS": "127.0.0.1,localhost",
    }
)

import uvicorn  # noqa: E402

from almabi_auth_store import AuthStore, BootstrapError  # noqa: E402

store = AuthStore(runtime / "auth.sqlite3")
try:
    store.bootstrap("visual-admin", "visual-admin-password")
except BootstrapError:
    store.update_password("visual-admin", "visual-admin-password")

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=18002, log_level="warning")
