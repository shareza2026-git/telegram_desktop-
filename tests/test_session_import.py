import sqlite3
from pathlib import Path

import pytest
from telethon.sessions import SQLiteSession

from app.telegram.session import SessionInfo
from app.telegram.session_import import SessionImporter


class StubSessions:
    def __init__(self, source: Path, target: Path) -> None:
        self.source = source
        self.target = target

    def source_file(self) -> Path | None:
        candidate = self.source
        if candidate.is_file():
            return candidate
        with_suffix = Path(str(candidate) + ".session")
        return with_suffix if with_suffix.is_file() else None

    def info(self) -> SessionInfo:
        target_candidates = (
            self.target,
            Path(str(self.target) + ".session"),
        )
        return SessionInfo(
            client_path=self.target,
            source_path=self.source,
            client_exists=any(path.is_file() for path in target_candidates),
            source_available=self.source_file() is not None,
        )

    def ensure_client_path(self) -> Path:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        return self.target

    def same_session(self, source: Path, target: Path) -> bool:
        source_values = {source.resolve(), Path(str(source) + ".session").resolve()}
        target_values = {target.resolve(), Path(str(target) + ".session").resolve()}
        return bool(source_values & target_values)

    def remove_client_session(self) -> None:
        for path in (self.target, Path(str(self.target) + ".session")):
            if path.is_file():
                path.unlink()


def make_source(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE sessions (
                dc_id INTEGER PRIMARY KEY,
                server_address TEXT,
                port INTEGER,
                auth_key BLOB,
                takeout_id INTEGER,
                tmp_auth_key BLOB
            )
            """
        )
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
            (2, "149.154.167.51", 443, b"t" * 256, None, b""),
        )


def test_import_reads_source_and_seeds_independent_session(tmp_path: Path):
    source = tmp_path / "dashboard.session"
    target = tmp_path / "client"
    make_source(source)

    SessionImporter(StubSessions(source, target)).import_source()

    imported = SQLiteSession(str(target))
    try:
        assert imported.dc_id == 2
        assert imported.server_address == "149.154.167.51"
        assert imported.port == 443
        assert imported.auth_key is not None
        assert imported.auth_key.key == b"t" * 256
    finally:
        imported.close()

    assert source.exists()


def test_import_refuses_existing_target(tmp_path: Path):
    source = tmp_path / "dashboard.session"
    target = tmp_path / "client"
    make_source(source)
    existing = SQLiteSession(str(target))
    existing.close()

    with pytest.raises(ValueError, match="already exists"):
        SessionImporter(StubSessions(source, target)).import_source()
