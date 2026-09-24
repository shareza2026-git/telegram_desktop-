from pathlib import Path

import pytest

from app.config import Settings


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
