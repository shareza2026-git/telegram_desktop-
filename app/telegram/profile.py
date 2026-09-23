from pathlib import Path
import time


CHAT_PHOTO_MAX_AGE_SECONDS = 60 * 60


def chat_photo_path(root: Path, chat_id: int) -> Path:
    return root / f"{chat_id}.jpg"


def is_fresh_chat_photo(
    path: Path,
    *,
    max_age_seconds: int = CHAT_PHOTO_MAX_AGE_SECONDS,
    now: float | None = None,
) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    current = time.time() if now is None else now
    return current - path.stat().st_mtime <= max_age_seconds
