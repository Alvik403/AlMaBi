from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
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
        validation_alias=AliasChoices("DEBUG", "OPOP_DEBUG"),
    )
    app_host: str = Field(
        default="0.0.0.0",
        validation_alias=AliasChoices("APP_HOST", "OPOP_APP_HOST"),
    )
    app_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("APP_PORT", "OPOP_APP_PORT"),
    )
    session_secret: str = Field(
        default="change-me-in-production",
        validation_alias=AliasChoices("SESSION_SECRET", "OPOP_SESSION_SECRET"),
    )

    data_dir: Path = Field(
        default=Path("data"),
        validation_alias=AliasChoices("DATA_DIR", "OPOP_DATA_DIR"),
    )
    uploads_dir: Path = Field(
        default=Path("uploads"),
        validation_alias=AliasChoices("UPLOADS_DIR", "OPOP_UPLOADS_DIR"),
    )
    database_path: Path = Field(
        default=Path("runtime/dashboard.sqlite3"),
        validation_alias=AliasChoices("DATABASE_PATH", "OPOP_DATABASE_PATH"),
    )
    logs_dir: Path = Field(
        default=Path("logs"),
        validation_alias=AliasChoices("LOGS_DIR", "OPOP_LOGS_DIR"),
    )
    active_default_file: str = Field(
        default="data.xlsx",
        validation_alias=AliasChoices("ACTIVE_DEFAULT_FILE", "OPOP_ACTIVE_DEFAULT_FILE"),
    )

    def resolve_path(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return BASE_DIR / path

    @property
    def resolved_data_dir(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def resolved_uploads_dir(self) -> Path:
        return self.resolve_path(self.uploads_dir)

    @property
    def resolved_database_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_logs_dir(self) -> Path:
        return self.resolve_path(self.logs_dir)

    @property
    def default_excel_path(self) -> Path:
        return self.resolved_data_dir / self.active_default_file

    def ensure_runtime_dirs(self) -> None:
        self.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_uploads_dir.mkdir(parents=True, exist_ok=True)
        self.resolved_database_path.parent.mkdir(parents=True, exist_ok=True)
        self.resolved_logs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_runtime_dirs()
    return settings
