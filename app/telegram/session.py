from dataclasses import dataclass
from pathlib import Path

from app.config import Settings


@dataclass(frozen=True)
class SessionInfo:
    client_path: Path
    source_path: Path | None
    client_exists: bool
    source_available: bool


class SessionManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def client_path(self) -> Path:
        return self.settings.telegram_session_path

    @property
    def source_path(self) -> Path | None:
        return self.settings.source_session_file

    @staticmethod
    def _session_file_candidates(path: Path | None) -> tuple[Path, ...]:
        if path is None:
            return ()
        values = [path]
        if path.suffix != ".session":
            values.append(Path(str(path) + ".session"))
        return tuple(dict.fromkeys(values))

    def source_file(self) -> Path | None:
        for candidate in self._session_file_candidates(self.source_path):
            if candidate.is_file():
                return candidate.resolve()
        return None

    def _client_candidates(self) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for base in self._session_file_candidates(self.client_path):
            candidates.extend(
                Path(str(base) + suffix)
                for suffix in ("", "-journal", "-wal", "-shm")
            )
        return tuple(dict.fromkeys(candidates))

    def same_session(self, source: Path, target: Path) -> bool:
        source_paths = {
            candidate.resolve()
            for candidate in self._session_file_candidates(source)
        }
        target_paths = {
            candidate.resolve()
            for candidate in self._session_file_candidates(target)
        }
        return bool(source_paths & target_paths)

    def ensure_client_path(self) -> Path:
        source = self.source_path
        target = self.client_path.resolve()
        if source is not None and self.same_session(source, target):
            raise ValueError("The desktop client session must not equal the source session")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def info(self) -> SessionInfo:
        source = self.source_path
        return SessionInfo(
            client_path=self.client_path,
            source_path=source,
            client_exists=any(path.is_file() for path in self._client_candidates()),
            source_available=self.source_file() is not None,
        )

    def remove_client_session(self) -> None:
        root = self.settings.data_root
        for candidate in self._client_candidates():
            candidate = candidate.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                candidate.unlink()
