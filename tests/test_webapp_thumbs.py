"""Lazy thumbnail generation for the search-history app."""

from __future__ import annotations

import pytest
from PIL import Image

from reverse_image_search_bot.webapp import thumbs


@pytest.fixture
def updir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(thumbs, "upload_dir", lambda: d)
    return d


def _image(path, size=(1200, 900), colour=(200, 30, 30)):
    Image.new("RGB", size, colour).save(path)
    return path


class TestGeneration:
    def test_creates_a_thumbnail_from_the_upload(self, updir):
        _image(updir / "F1.jpg")
        out = thumbs.get_or_create("F1", "F1.jpg")
        assert out is not None and out.is_file()
        with Image.open(out) as im:
            assert im.format == "WEBP"
            assert max(im.size) <= max(thumbs.THUMB_SIZE)

    def test_preserves_aspect_ratio(self, updir):
        _image(updir / "F1.jpg", size=(1200, 300))
        out = thumbs.get_or_create("F1", "F1.jpg")
        assert out is not None
        with Image.open(out) as im:
            assert im.size == (320, 80)

    def test_is_much_smaller_than_the_original(self, updir):
        src = _image(updir / "F1.jpg", size=(2000, 2000))
        out = thumbs.get_or_create("F1", "F1.jpg")
        assert out is not None
        assert out.stat().st_size < src.stat().st_size

    def test_lands_in_a_subdirectory_of_the_upload_dir(self, updir):
        """Subdirectories are skipped by the retention sweep — that is the point."""
        _image(updir / "F1.jpg")
        out = thumbs.get_or_create("F1", "F1.jpg")
        assert out is not None
        assert out.parent == updir / "thumbs"
        assert out.parent.parent == updir

    def test_second_call_reuses_the_cached_file(self, updir):
        _image(updir / "F1.jpg")
        first = thumbs.get_or_create("F1", "F1.jpg")
        assert first is not None
        stamp = first.stat().st_mtime_ns
        # Remove the source: a re-render would now be impossible, so an identical
        # result proves the cached file was served rather than rebuilt.
        (updir / "F1.jpg").unlink()
        second = thumbs.get_or_create("F1", "F1.jpg")
        assert second is not None
        assert second == first
        assert second.stat().st_mtime_ns == stamp

    def test_transparent_source_is_flattened_not_crashed(self, updir):
        Image.new("RGBA", (400, 400), (0, 0, 0, 0)).save(updir / "F1.png")
        assert thumbs.get_or_create("F1", "F1.png") is not None


class TestMissingAndBroken:
    def test_swept_upload_yields_none(self, updir):
        """Retention removed the original; the entry stays, the image does not."""
        assert thumbs.get_or_create("GONE", "GONE.jpg") is None

    def test_no_saved_filename_yields_none(self, updir):
        assert thumbs.get_or_create("F1", None) is None
        assert thumbs.get_or_create("F1", "") is None

    def test_corrupt_file_yields_none_and_leaves_no_stub(self, updir):
        (updir / "F1.jpg").write_bytes(b"this is not an image")
        assert thumbs.get_or_create("F1", "F1.jpg") is None
        assert not (updir / "thumbs" / "F1.webp").exists()

    def test_no_uploader_configured_yields_none(self, monkeypatch):
        monkeypatch.setattr(thumbs, "upload_dir", lambda: None)
        assert thumbs.get_or_create("F1", "F1.jpg") is None
        assert thumbs.thumb_path("F1") is None


class TestPathSafety:
    def test_traversal_in_the_stored_filename_is_refused(self, updir, tmp_path):
        """saved_filename comes from the DB; it must not reach outside the dir."""
        secret = tmp_path / "secret.jpg"
        _image(secret)
        assert thumbs.get_or_create("EVIL", "../secret.jpg") is None

    def test_absolute_path_is_refused(self, updir, tmp_path):
        secret = _image(tmp_path / "secret.jpg")
        assert thumbs.get_or_create("EVIL", str(secret)) is None


class TestDeletion:
    def test_deletes_thumbnails_for_the_given_files(self, updir):
        _image(updir / "A.jpg")
        _image(updir / "B.jpg")
        thumbs.get_or_create("A", "A.jpg")
        thumbs.get_or_create("B", "B.jpg")
        assert thumbs.delete_for_files(["A"]) == 1
        assert not (updir / "thumbs" / "A.webp").exists()
        assert (updir / "thumbs" / "B.webp").exists()

    def test_deleting_a_missing_thumbnail_is_not_an_error(self, updir):
        assert thumbs.delete_for_files(["NOPE"]) == 0
