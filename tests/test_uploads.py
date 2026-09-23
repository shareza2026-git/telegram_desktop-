from io import BytesIO

import pytest

from app.telegram.uploads import cleanup_staged_upload, stage_upload


def test_stage_upload_sanitizes_name_and_keeps_content(tmp_path):
    staged = stage_upload(
        BytesIO(b"telegram"),
        tmp_path / "uploads",
        "../../report.pdf",
        max_bytes=100,
    )

    assert staged.filename == "report.pdf"
    assert staged.path.parent == tmp_path / "uploads"
    assert staged.path.name.endswith("_report.pdf")
    assert staged.path.read_bytes() == b"telegram"
    assert staged.size == 8

    cleanup_staged_upload(staged.path)
    assert staged.path.exists() is False


def test_stage_upload_rejects_empty_file(tmp_path):
    with pytest.raises(ValueError, match="Empty"):
        stage_upload(BytesIO(b""), tmp_path, "empty.txt", max_bytes=100)

    assert list(tmp_path.iterdir()) == []


def test_stage_upload_removes_partial_file_when_limit_is_exceeded(tmp_path):
    with pytest.raises(ValueError, match="2 GB"):
        stage_upload(BytesIO(b"12345"), tmp_path, "large.bin", max_bytes=4)

    assert list(tmp_path.iterdir()) == []
