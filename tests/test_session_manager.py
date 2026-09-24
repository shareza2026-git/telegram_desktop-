from types import SimpleNamespace

from app.telegram.session import SessionManager


def test_remove_client_session_keeps_source_session_untouched(tmp_path):
    root = tmp_path / "project"
    client = root / "data" / "telegram_desktop" / "accounts" / "default" / "client"
    source = tmp_path / "dashboard.session"
    client.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    for suffix in ("", "-journal", "-wal", "-shm"):
        client.with_name(client.name + suffix).write_bytes(b"client")

    settings = SimpleNamespace(
        project_root=root,
        data_root=root / "data" / "telegram_desktop",
        telegram_session_path=client,
        source_session_file=source,
    )
    manager = SessionManager(settings)

    manager.remove_client_session()

    assert source.read_bytes() == b"source"
    assert manager.info().client_exists is False
    assert manager.info().source_available is True
