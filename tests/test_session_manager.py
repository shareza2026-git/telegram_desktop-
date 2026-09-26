from types import SimpleNamespace

from app.telegram.session import SessionManager
from telethon.crypto import AuthKey
from telethon.sessions import MemorySession


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


def test_authorized_memory_session_is_persisted_for_next_launch(tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    settings = SimpleNamespace(telegram_session_path=root / "client")
    manager = SessionManager(settings)
    runtime = MemorySession()
    runtime.set_dc(2, "149.154.167.51", 443)
    runtime.auth_key = AuthKey(data=b"x" * 256)

    manager.persist_runtime_session(runtime)
    restored, metadata = manager.clone_runtime_session()

    assert metadata["auth_key_bytes"] == 256
    assert restored is not None and restored.auth_key.key == b"x" * 256
