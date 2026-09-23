from app.models import MediaInfo
from app.telegram.media import media_path, safe_media_name


def test_safe_media_name_removes_path_components():
    assert safe_media_name("../../private.session") == "private.session"
    assert safe_media_name(r"..\private.session") == "private.session"


def test_media_path_stays_in_download_root(tmp_path):
    root = tmp_path / "downloads"
    target = media_path(root, -100, 7, "../../photo.jpg")

    assert target.parent == root
    assert target.name == "-100_7_photo.jpg"
    assert target.resolve().is_relative_to(root.resolve())


def test_media_is_downloadable_but_not_playable():
    value = MediaInfo(kind="photo")

    assert value.downloadable is True
    assert value.playable is False
