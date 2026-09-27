import json
import sqlite3

from app.desktop import _restore_portable_state, _session_has_auth_key


def _write_session(path, auth_key: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path))
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                dc_id INTEGER PRIMARY KEY,
                server_address TEXT,
                port INTEGER,
                auth_key BLOB
            )
            """
        )
        connection.execute("DELETE FROM sessions")
        connection.execute(
            "INSERT INTO sessions(dc_id, server_address, port, auth_key) VALUES (?, ?, ?, ?)",
            (2, "149.154.167.51", 443, auth_key),
        )
        connection.commit()
    finally:
        connection.close()


def test_restore_portable_state_replaces_stale_appdata_session(tmp_path):
    data_root = tmp_path / "appdata"
    transfer_dir = tmp_path / "installed"
    local_session = data_root / "accounts" / "default" / "client.session"
    portable_session = transfer_dir / "telegram-session.session"

    _write_session(local_session, None)
    _write_session(portable_session, b"x" * 256)

    transfer_dir.mkdir(parents=True, exist_ok=True)
    (transfer_dir / "telegram-api.env").write_text(
        "TELEGRAM_API_ID=123\nTELEGRAM_API_HASH=abcdef0123456789\n",
        encoding="utf-8",
    )
    (transfer_dir / "telegram-proxies.json").write_text(
        json.dumps({"proxies": [{"type": "socks5", "host": "127.0.0.1", "port": 1080}]}),
        encoding="utf-8",
    )

    _restore_portable_state(data_root, transfer_dir)

    assert _session_has_auth_key(local_session) is True
    assert (data_root / "settings.env").read_text(encoding="utf-8").startswith("TELEGRAM_API_ID=123")
    assert json.loads((data_root / "proxies.json").read_text(encoding="utf-8"))["proxies"]


def test_restore_portable_state_ignores_invalid_portable_session(tmp_path):
    data_root = tmp_path / "appdata"
    transfer_dir = tmp_path / "installed"
    local_session = data_root / "accounts" / "default" / "client.session"
    portable_session = transfer_dir / "telegram-session.session"

    _write_session(local_session, b"l" * 256)
    _write_session(portable_session, None)

    _restore_portable_state(data_root, transfer_dir)

    assert _session_has_auth_key(local_session) is True


def test_restore_keeps_current_account_and_local_proxy_changes(tmp_path):
    data_root = tmp_path / "appdata"
    transfer_dir = tmp_path / "installed"
    local_session = data_root / "accounts" / "default" / "client.session"
    portable_session = transfer_dir / "telegram-session.session"
    _write_session(local_session, b"l" * 256)
    _write_session(portable_session, b"p" * 256)
    (data_root / "settings.env").write_text("current-api", encoding="utf-8")
    (data_root / "proxies.json").write_text('{"proxies":[]}', encoding="utf-8")
    (transfer_dir / "telegram-api.env").write_text("stale-api", encoding="utf-8")
    (transfer_dir / "telegram-proxies.json").write_text('{"proxies":[{"type":"socks5"}]}', encoding="utf-8")

    _restore_portable_state(data_root, transfer_dir)

    with sqlite3.connect(local_session) as connection:
        assert connection.execute("SELECT auth_key FROM sessions").fetchone()[0] == b"l" * 256
    assert (data_root / "settings.env").read_text(encoding="utf-8") == "current-api"
    assert (data_root / "proxies.json").read_text(encoding="utf-8") == '{"proxies":[]}'
