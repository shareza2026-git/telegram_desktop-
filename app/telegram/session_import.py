import sqlite3
from pathlib import Path
from urllib.parse import quote

from telethon.crypto import AuthKey
from telethon.sessions import SQLiteSession

from app.telegram.session import SessionManager


class SessionImporter:
    """Read a Telethon session without opening it for write and seed a new session."""

    def __init__(self, sessions: SessionManager) -> None:
        self.sessions = sessions

    @staticmethod
    def _read_authorization(source: Path) -> tuple[int, str, int, bytes]:
        uri = f"file:{quote(source.resolve().as_posix(), safe='/:')}?mode=ro"
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=5.0)
            row = connection.execute(
                "SELECT dc_id, server_address, port, auth_key "
                "FROM sessions LIMIT 1"
            ).fetchone()
        except (OSError, sqlite3.Error, ValueError):
            raise ValueError("Source session could not be read") from None
        finally:
            if connection is not None:
                connection.close()

        if not row or not row[3]:
            raise ValueError("Source session is not authorized")
        try:
            return int(row[0]), str(row[1]), int(row[2]), bytes(row[3])
        except (TypeError, ValueError):
            raise ValueError("Source session is invalid") from None

    def import_source(self) -> Path:
        info = self.sessions.info()
        if info.client_exists:
            raise ValueError("Desktop session already exists")
        source = self.sessions.source_file()
        if source is None:
            raise ValueError("Source session was not found")

        target = self.sessions.ensure_client_path()
        if self.sessions.same_session(source, target):
            raise ValueError("The desktop client session must not equal the source session")

        dc_id, server_address, port, auth_key = self._read_authorization(source)
        target_session: SQLiteSession | None = None
        failed = True
        try:
            target_session = SQLiteSession(str(target))
            target_session.set_dc(dc_id, server_address, port)
            target_session.auth_key = AuthKey(data=auth_key)
            target_session.save()
            failed = False
        except Exception:
            raise ValueError("Desktop session import failed") from None
        finally:
            if target_session is not None:
                target_session.close()
            if failed:
                self.sessions.remove_client_session()

        return target
