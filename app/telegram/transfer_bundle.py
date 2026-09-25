from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from app.config import Settings
from app.telegram.transport import TransportCatalog


logger = logging.getLogger(__name__)


class TransferBundle:
    def __init__(self, settings: Settings, transport: TransportCatalog) -> None:
        self.settings = settings
        self.transport = transport

    @property
    def root(self) -> Path | None:
        value = self.settings.telegram_transfer_dir
        if value is None:
            return None
        return value.resolve()

    def _write_api(self, root: Path) -> None:
        if not self.settings.telegram_configured:
            return
        api_hash = self.settings.telegram_api_hash.get_secret_value()
        text = (
            f"TELEGRAM_API_ID={self.settings.telegram_api_id}\n"
            f"TELEGRAM_API_HASH={api_hash}\n"
            f"TELEGRAM_ALLOW_DIRECT={'true' if self.settings.telegram_allow_direct else 'false'}\n"
        )
        (root / "telegram-api.env").write_text(text, encoding="utf-8")

    def _write_proxies(self, root: Path) -> None:
        payload = {"proxies": self.transport.export_records()}
        (root / "telegram-proxies.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _snapshot_session(self, root: Path) -> None:
        source = self.settings.telegram_session_path
        candidates = [source]
        if source.suffix != ".session":
            candidates.append(Path(str(source) + ".session"))
        source_file = next((path for path in candidates if path.is_file()), None)
        if source_file is None:
            return

        target = root / "telegram-session.session"
        temporary = root / "telegram-session.session.tmp"
        temporary.unlink(missing_ok=True)

        src = sqlite3.connect(str(source_file))
        dst = sqlite3.connect(str(temporary))
        try:
            src.backup(dst)
            dst.commit()
        finally:
            dst.close()
            src.close()

        check = sqlite3.connect(str(temporary))
        try:
            row = check.execute(
                "SELECT dc_id, server_address, port, length(auth_key) FROM sessions LIMIT 1"
            ).fetchone()
        finally:
            check.close()

        if not row or not row[3] or int(row[3]) < 64:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Telegram transfer session does not contain a usable auth key")

        temporary.replace(target)

    def sync(self, *, include_session: bool = True) -> None:
        root = self.root
        if root is None:
            return
        try:
            root.mkdir(parents=True, exist_ok=True)
            self._write_api(root)
            self._write_proxies(root)
            if include_session:
                self._snapshot_session(root)
        except Exception:
            logger.warning("Telegram transfer bundle could not be synchronized", exc_info=True)

    def remove_session(self) -> None:
        root = self.root
        if root is None:
            return
        try:
            (root / "telegram-session.session").unlink(missing_ok=True)
        except Exception:
            logger.warning("Telegram transfer session could not be removed", exc_info=True)
