from dataclasses import dataclass
from pathlib import Path
import re


_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class DownloadedMedia:
    path: Path
    filename: str
    mime_type: str | None


def safe_media_name(name: str | None, fallback: str = "media") -> str:
    """Return an ASCII filename that cannot contain a path component."""
    candidate = Path(name or "").name
    candidate = _UNSAFE_FILENAME_CHARS.sub("_", candidate).strip("._")
    return candidate or fallback


def media_path(root: Path, chat_id: int, message_id: int, filename: str) -> Path:
    safe_name = safe_media_name(filename, fallback=f"media_{message_id}")
    return root / f"{chat_id}_{message_id}_{safe_name}"
