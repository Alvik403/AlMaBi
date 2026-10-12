from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = Field(
        default=False,
        validation_alias="DEBUG",
    )
    app_host: str = Field(
        default="0.0.0.0",
        validation_alias="APP_HOST",
    )
    app_port: int = Field(
        default=8000,
        validation_alias="APP_PORT",
    )
    session_secret: str = Field(
        default="change-me-in-production",
        validation_alias="SESSION_SECRET",
    )
    session_secret_file: Path | None = Field(
        default=None,
        validation_alias="SESSION_SECRET_FILE",
    )
    data_key_file: Path | None = Field(
        default=None,
        validation_alias="DATA_KEY_FILE",
    )
    upload_data_key: bytes | None = Field(
        default=None,
        validation_alias="ALMABI_UPLOAD_DATA_KEY_UNUSED",
    )
    session_max_age_seconds: int = Field(
        default=8 * 60 * 60,
        validation_alias="SESSION_MAX_AGE_SECONDS",
    )
    session_idle_seconds: int = Field(
        default=15 * 60,
        validation_alias="SESSION_IDLE_SECONDS",
    )
    secret_max_age_days: int = Field(
        default=60,
        validation_alias="SECRET_MAX_AGE_DAYS",
    )
    session_https_only: bool = Field(
        default=False,
        validation_alias="SESSION_HTTPS_ONLY",
    )
    auth_enabled: bool = Field(
        default=True,
        validation_alias="AUTH_ENABLED",
    )
    auth_db: Path = Field(
        default=Path("runtime/auth.sqlite3"),
        validation_alias="AUTH_DB",
    )
    auth_database_url: str = Field(
        default="",
        validation_alias="AUTH_DATABASE_URL",
    )
    auth_database_password_file: Path | None = Field(
        default=None,
        validation_alias="AUTH_DATABASE_PASSWORD_FILE",
    )
    tls_cert_file: Path | None = Field(
        default=None,
        validation_alias="TLS_CERT_FILE",
    )
    keycloak_issuer: str = Field(
        default="",
        validation_alias="KEYCLOAK_ISSUER",
    )
    keycloak_internal_issuer: str = Field(
        default="",
        validation_alias="KEYCLOAK_INTERNAL_ISSUER",
    )
    keycloak_client_id: str = Field(
        default="",
        validation_alias="KEYCLOAK_CLIENT_ID",
    )
    keycloak_client_secret: str = Field(
        default="",
        validation_alias="KEYCLOAK_CLIENT_SECRET",
    )
    keycloak_client_secret_file: Path | None = Field(
        default=None,
        validation_alias="KEYCLOAK_CLIENT_SECRET_FILE",
    )
    keycloak_redirect_uri: str = Field(
        default="",
        validation_alias="KEYCLOAK_REDIRECT_URI",
    )
    retention_interval_days: int = Field(
        default=10,
        validation_alias="RETENTION_INTERVAL_DAYS",
    )
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        validation_alias="MAX_UPLOAD_BYTES",
    )
    request_timeout_seconds: int = Field(
        default=900,
        validation_alias="REQUEST_TIMEOUT_SECONDS",
    )
    uvicorn_workers: int = Field(
        default=1,
        validation_alias="UVICORN_WORKERS",
    )
    dashboard_cache_max_entries: int = Field(
        default=8,
        validation_alias="DASHBOARD_CACHE_MAX_ENTRIES",
    )
    dashboard_skip_deep_copy: bool = Field(
        default=True,
        validation_alias="DASHBOARD_SKIP_DEEP_COPY",
    )
    pipeline_skip_audit_when_disabled: bool = Field(
        default=True,
        validation_alias="PIPELINE_SKIP_AUDIT_WHEN_DISABLED",
    )
    perf_log_enabled: bool = Field(
        default=False,
        validation_alias="PERF_LOG_ENABLED",
    )
    upload_quota_bytes: int = Field(
        default=500 * 1024 * 1024,
        validation_alias="UPLOAD_QUOTA_BYTES",
    )
    audit_detail_enabled: bool = Field(
        default=False,
        validation_alias="AUDIT_DETAIL_ENABLED",
    )
    upload_retention_days: int = Field(
        default=90,
        validation_alias="UPLOAD_RETENTION_DAYS",
    )
    log_retention_days: int = Field(
        default=30,
        validation_alias="LOG_RETENTION_DAYS",
    )
    allowed_hosts: str = Field(
        default="localhost,127.0.0.1,testserver",
        validation_alias="ALLOWED_HOSTS",
    )

    uploads_dir: Path = Field(
        default=Path("uploads"),
        validation_alias="UPLOADS_DIR",
    )
    runtime_dir: Path = Field(
        default=Path("runtime"),
        validation_alias="RUNTIME_DIR",
    )
    logs_dir: Path = Field(
        default=Path("logs"),
        validation_alias="LOGS_DIR",
    )
    log_to_files: bool = Field(
        default=True,
        validation_alias="LOG_TO_FILES",
    )

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return BASE_DIR / path

    @property
    def resolved_uploads_dir(self) -> Path:
        return self.resolve_path(self.uploads_dir)

    @property
    def resolved_runtime_dir(self) -> Path:
        return self.resolve_path(self.runtime_dir)

    @property
    def resolved_logs_dir(self) -> Path:
        return self.resolve_path(self.logs_dir)

    @property
    def resolved_auth_db(self) -> Path:
        return self.resolve_path(self.auth_db)

    @property
    def allowed_host_list(self) -> list[str]:
        return [value.strip() for value in self.allowed_hosts.split(",") if value.strip()]

    @property
    def keycloak_enabled(self) -> bool:
        return bool(self.keycloak_issuer.strip() and self.keycloak_client_id.strip() and self.keycloak_client_secret.strip())

    @property
    def resolved_auth_database_url(self) -> str:
        url = self.auth_database_url.strip()
        if not url or self.auth_database_password_file is None:
            return url
        password = self.resolve_path(self.auth_database_password_file).read_text(encoding="utf-8").strip()
        return _inject_url_password(url, password)

    @model_validator(mode="after")
    def apply_secret_files(self) -> "Settings":
        if self.session_secret_file is not None:
            secret_path = self.resolve_path(self.session_secret_file)
            if secret_path.is_file():
                object.__setattr__(
                    self,
                    "session_secret",
                    secret_path.read_text(encoding="utf-8").strip(),
                )
        if self.keycloak_client_secret_file is not None:
            secret_path = self.resolve_path(self.keycloak_client_secret_file)
            if secret_path.is_file():
                object.__setattr__(
                    self,
                    "keycloak_client_secret",
                    secret_path.read_text(encoding="utf-8").strip(),
                )
        key: bytes | None = None
        if self.data_key_file is not None:
            key_path = self.resolve_path(self.data_key_file)
            if key_path.is_file():
                from almabi_file_crypto import read_key_material

                key = read_key_material(key_path)
        object.__setattr__(self, "upload_data_key", key)
        return self

    def ensure_runtime_dirs(self) -> None:
        for path in (
            self.resolved_uploads_dir,
            self.resolved_runtime_dir,
            self.resolved_logs_dir,
            self.resolved_auth_db.parent,
        ):
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError:
                # Bind-mounts on Windows/macOS may exist but be unwritable for the app user.
                continue

    def validate_security(self) -> None:
        if self.auth_enabled and not self.debug:
            if self.session_secret_file is None or not self.resolve_path(self.session_secret_file).is_file():
                raise RuntimeError(
                    "SESSION_SECRET_FILE is required when authentication is enabled outside debug mode"
                )
            if self.session_secret == "change-me-in-production" or len(self.session_secret) < 32:
                raise RuntimeError(
                    "SESSION_SECRET must contain at least 32 characters when authentication is enabled"
                )
            if not self.session_https_only:
                raise RuntimeError(
                    "SESSION_HTTPS_ONLY must be true when authentication is enabled outside debug mode"
                )
            if self.upload_data_key is None:
                raise RuntimeError(
                    "DATA_KEY_FILE is required when authentication is enabled outside debug mode"
                )
            if not self.keycloak_enabled:
                raise RuntimeError(
                    "KEYCLOAK_ISSUER, KEYCLOAK_CLIENT_ID and client secret are required when authentication is enabled outside debug mode"
                )
        if self.max_upload_bytes <= 0:
            raise RuntimeError("MAX_UPLOAD_BYTES must be greater than zero")
        if self.upload_quota_bytes < self.max_upload_bytes:
            raise RuntimeError("UPLOAD_QUOTA_BYTES must be greater than or equal to MAX_UPLOAD_BYTES")
        if self.request_timeout_seconds <= 0:
            raise RuntimeError("REQUEST_TIMEOUT_SECONDS must be greater than zero")
        if self.uvicorn_workers <= 0:
            raise RuntimeError("UVICORN_WORKERS must be greater than zero")
        if self.dashboard_cache_max_entries <= 0:
            raise RuntimeError("DASHBOARD_CACHE_MAX_ENTRIES must be greater than zero")


from almabi_file_crypto import configure_data_key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security()
    settings.ensure_runtime_dirs()
    configure_data_key(settings.upload_data_key)
    return settings


def _inject_url_password(url: str, password: str) -> str:
    from urllib.parse import quote, urlsplit, urlunsplit

    parts = urlsplit(url)
    if parts.password:
        return url
    username = parts.username or ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
