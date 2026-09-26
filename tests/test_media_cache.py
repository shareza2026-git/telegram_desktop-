from pathlib import Path

from app.telegram.media import cached_media_path


def test_cached_media_path_returns_existing_nonempty_file(tmp_path: Path):
    target = tmp_path / "123_456_photo.jpg"
    target.write_bytes(b"data")

    assert cached_media_path(tmp_path, 123, 456) == target


def test_cached_media_path_ignores_empty_or_other_message_files(tmp_path: Path):
    (tmp_path / "123_456_empty.jpg").write_bytes(b"")
    (tmp_path / "123_999_other.jpg").write_bytes(b"data")

    assert cached_media_path(tmp_path, 123, 456) is None
