from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic import Field, SecretStr, field_validator, model_validator
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
    telegram_client_data_root: Path | None = Field(
        default=None,
        validation_alias="TELEGRAM_CLIENT_DATA_ROOT",
    )
    telegram_transfer_dir: Path | None = Field(
        default=None,
        validation_alias="TELEGRAM_TRANSFER_DIR",
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

    @field_validator(
        "telegram_api_id",
        "telegram_api_hash",
        "telegram_client_data_root",
        "telegram_transfer_dir",
        "telegram_source_session_path",
        mode="before",
    )
    @classmethod
    def empty_optional_value(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @model_validator(mode="after")
    def keep_local_data_under_client_root(self):
        allowed = self.data_root

        def resolve(value: Path) -> Path:
            if value.is_absolute():
                resolved = value.resolve()
            else:
                parts = value.parts
                if parts[:2] == ("data", "telegram_desktop"):
                    value = Path(*parts[2:])
                resolved = (allowed / value).resolve()
            if not resolved.is_relative_to(allowed):
                raise ValueError("Client session and database must stay inside the client data root")
            return resolved

        self.telegram_session_path = resolve(self.telegram_session_path)
        self.database_path = resolve(self.database_path)
        return self

    @model_validator(mode="after")
    def reuse_dashboard_api_config_read_only(self):
        if self.telegram_api_id and self.telegram_api_hash:
            return self
        catalog = self.telegram_proxy_config
        if not catalog.is_absolute():
            catalog = self.project_root / catalog
        try:
            catalog = catalog.resolve()
            if not catalog.is_file():
                return self
            dashboard_env = catalog.parents[2] / ".env"
            values = dotenv_values(dashboard_env) if dashboard_env.is_file() else {}
            if self.telegram_api_id is None and str(values.get("TG_API_ID") or "").strip():
                self.telegram_api_id = int(str(values["TG_API_ID"]).strip())
            if self.telegram_api_hash is None and str(values.get("TG_API_HASH") or "").strip():
                self.telegram_api_hash = SecretStr(str(values["TG_API_HASH"]).strip())
        except (IndexError, TypeError, ValueError, OSError):
            pass
        return self

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash)

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def data_root(self) -> Path:
        if self.telegram_client_data_root is None:
            return (self.project_root / "data" / "telegram_desktop").resolve()
        value = self.telegram_client_data_root
        return (self.project_root / value).resolve() if not value.is_absolute() else value.resolve()

    @property
    def source_session_file(self) -> Path | None:
        if self.telegram_source_session_path is None:
            return None
        value = self.telegram_source_session_path
        return (self.project_root / value).resolve() if not value.is_absolute() else value.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
