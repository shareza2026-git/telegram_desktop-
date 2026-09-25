from pathlib import Path

import pytest

from app.config import Settings


def test_blank_optional_environment_values_keep_client_unconfigured(tmp_path: Path):
    settings = Settings(
        TELEGRAM_API_ID="",
        TELEGRAM_API_HASH="  ",
        TELEGRAM_CLIENT_DATA_ROOT="",
        TELEGRAM_SOURCE_SESSION_PATH="",
        TELEGRAM_PROXY_CONFIG=str(tmp_path / "missing.json"),
    )

    assert settings.telegram_api_id is None
    assert settings.telegram_api_hash is None
    assert settings.telegram_client_data_root is None
    assert settings.telegram_source_session_path is None
    assert settings.telegram_configured is False
    assert settings.data_root == settings.project_root / "data" / "telegram_desktop"


def test_client_paths_follow_explicit_writable_data_root(tmp_path: Path):
    data_root = tmp_path / "client-data"
    settings = Settings(
        TELEGRAM_CLIENT_DATA_ROOT=str(data_root),
        TELEGRAM_SESSION_PATH="accounts/default/client",
        TELEGRAM_DATABASE_PATH="accounts/default/client.db",
    )

    assert settings.data_root == data_root.resolve()
    assert settings.telegram_session_path == data_root / "accounts" / "default" / "client"
    assert settings.database_path == data_root / "accounts" / "default" / "client.db"


def test_client_paths_cannot_escape_data_root(tmp_path: Path):
    data_root = tmp_path / "client-data"
    with pytest.raises(ValueError, match="client data root"):
        Settings(
            TELEGRAM_CLIENT_DATA_ROOT=str(data_root),
            TELEGRAM_SESSION_PATH=str(tmp_path / "outside.session"),
        )


def test_missing_api_credentials_are_read_from_dashboard_env(tmp_path: Path):
    dashboard = tmp_path / "DASHBOARD"
    catalog = dashboard / "data" / "config" / "connection_routes.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text('{"version":1,"direct":{},"routes":[]}', encoding="utf-8")
    (dashboard / ".env").write_text("TG_API_ID=12345\nTG_API_HASH=dashboard-hash\n", encoding="utf-8")

    settings = Settings(
        TELEGRAM_API_ID="",
        TELEGRAM_API_HASH="",
        TELEGRAM_PROXY_CONFIG=str(catalog),
        TELEGRAM_CLIENT_DATA_ROOT=str(tmp_path / "client-data"),
    )

    assert settings.telegram_api_id == 12345
    assert settings.telegram_api_hash is not None
    assert settings.telegram_api_hash.get_secret_value() == "dashboard-hash"
    assert settings.telegram_configured is True
