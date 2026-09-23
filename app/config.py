from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    telegram_api_id: int | None = Field(
        default=None,
        validation_alias="TELEGRAM_API_ID",
        ge=1,
    )
    telegram_api_hash: SecretStr | None = Field(
        default=None,
        validation_alias="TELEGRAM_API_HASH",
    )
    telegram_session_path: Path = Field(
        default=Path("data/telegram_desktop/accounts/default/client"),
        validation_alias="TELEGRAM_SESSION_PATH",
    )
    telegram_source_session_path: Path | None = Field(
        default=None,
        validation_alias="TELEGRAM_SOURCE_SESSION_PATH",
    )
    telegram_auto_import_source: bool = Field(
        default=False,
        validation_alias="TELEGRAM_AUTO_IMPORT_SOURCE",
    )
    telegram_proxy_config: Path = Field(
        default=Path("data/telegram/proxies.json"),
        validation_alias="TELEGRAM_PROXY_CONFIG",
    )
    telegram_allow_direct: bool = Field(
        default=False,
        validation_alias="TELEGRAM_ALLOW_DIRECT",
    )
    backend_host: str = Field(
        default="127.0.0.1",
        validation_alias="TELEGRAM_BACKEND_HOST",
    )
    backend_port: int = Field(
        default=8110,
        validation_alias="TELEGRAM_BACKEND_PORT",
        ge=1,
        le=65535,
    )
    database_path: Path = Field(
        default=Path("data/telegram_desktop/accounts/default/client.db"),
        validation_alias="TELEGRAM_DATABASE_PATH",
    )

    @field_validator("telegram_source_session_path", mode="before")
    @classmethod
    def empty_source_path(cls, value):
        return None if value in (None, "") else value

    @field_validator("telegram_session_path", "database_path")
    @classmethod
    def keep_local_data_under_client_root(cls, value: Path) -> Path:
        root = Path(__file__).resolve().parents[1]
        resolved = (root / value).resolve() if not value.is_absolute() else value.resolve()
        allowed = (root / "data" / "telegram_desktop").resolve()
        if not resolved.is_relative_to(allowed):
            raise ValueError("Client session and database must stay inside data/telegram_desktop")
        return resolved

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash)

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def source_session_file(self) -> Path | None:
        if self.telegram_source_session_path is None:
            return None
        value = self.telegram_source_session_path
        return (self.project_root / value).resolve() if not value.is_absolute() else value.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
