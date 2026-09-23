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

    def ensure_client_path(self) -> Path:
        source = self.source_path
        target = self.client_path.resolve()
        if source is not None and source.resolve() == target:
            raise ValueError("The desktop client session must not equal the source session")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _client_candidates(self) -> tuple[Path, ...]:
        bases = {self.client_path, Path(str(self.client_path) + ".session")}
        candidates = []
        for base in bases:
            candidates.extend(Path(str(base) + suffix) for suffix in ("", "-journal", "-wal", "-shm"))
        return tuple(candidates)

    def info(self) -> SessionInfo:
        source = self.source_path
        return SessionInfo(
            client_path=self.client_path,
            source_path=source,
            client_exists=any(path.is_file() for path in self._client_candidates()),
            source_available=bool(source and source.exists()),
        )

    def remove_client_session(self) -> None:
        root = (self.settings.project_root / "data" / "telegram_desktop").resolve()
        for candidate in self._client_candidates():
            candidate = candidate.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                candidate.unlink()
