from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    session_max_age_seconds: int = Field(
        default=8 * 60 * 60,
        validation_alias="SESSION_MAX_AGE_SECONDS",
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
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        validation_alias="MAX_UPLOAD_BYTES",
    )
    request_timeout_seconds: int = Field(
        default=300,
        validation_alias="REQUEST_TIMEOUT_SECONDS",
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
            if self.session_secret == "change-me-in-production" or len(self.session_secret) < 32:
                raise RuntimeError(
                    "SESSION_SECRET must contain at least 32 characters when authentication is enabled"
                )
            if not self.session_https_only:
                raise RuntimeError(
                    "SESSION_HTTPS_ONLY must be true when authentication is enabled outside debug mode"
                )
        if self.max_upload_bytes <= 0:
            raise RuntimeError("MAX_UPLOAD_BYTES must be greater than zero")
        if self.upload_quota_bytes < self.max_upload_bytes:
            raise RuntimeError("UPLOAD_QUOTA_BYTES must be greater than or equal to MAX_UPLOAD_BYTES")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_security()
    settings.ensure_runtime_dirs()
    return settings
