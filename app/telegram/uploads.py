from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.telegram.media import safe_media_name


MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class StagedUpload:
    path: Path
    filename: str
    size: int


def stage_upload(
    source: BinaryIO,
    root: Path,
    filename: str | None,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> StagedUpload:
    safe_name = safe_media_name(filename, fallback="attachment")
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{uuid4().hex}_{safe_name}"
    total = 0

    try:
        source.seek(0)
        with target.open("xb") as destination:
            while True:
                chunk = source.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("File exceeds the 2 GB upload limit")
                destination.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    if total == 0:
        target.unlink(missing_ok=True)
        raise ValueError("Empty files cannot be uploaded")

    return StagedUpload(path=target, filename=safe_name, size=total)


def cleanup_staged_upload(path: Path) -> None:
    path.unlink(missing_ok=True)
