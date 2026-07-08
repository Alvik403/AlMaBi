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

    def ensure_runtime_dirs(self) -> None:
        self.resolved_uploads_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_runtime_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_logs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
