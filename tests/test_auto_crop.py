"""image_to_url with auto_crop: screenshots go up cropped, everything else untouched."""

from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from telegram import PhotoSize
from yarl import URL


def _photo_bytes(size=(64, 64), color=(200, 30, 30)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "jpeg")
    return buf.getvalue()


def _screenshot_bytes() -> bytes:
    # autocrop-rs's showcase image: a phone screenshot of a tweet with an embedded clip.
    return (Path(__file__).parent / "fixtures" / "screenshot.jpg").read_bytes()


def _photo() -> PhotoSize:
    photo = MagicMock(spec=PhotoSize)
    photo.file_unique_id = "shot1"
    return photo


@pytest.fixture
def uploaded():
    """Patch the upload path; yields the list of (filename, size) that got uploaded."""
    from reverse_image_search_bot.commands import utils

    calls = []

    def upload(file, filename):
        calls.append((filename, Image.open(file).size))
        return URL(f"https://u.test/{filename}")

    with (
        patch.object(utils.uploader, "file_exists", return_value=False),
        patch.object(utils, "upload_file", side_effect=upload),
    ):
        yield calls


@pytest.mark.parametrize(
    ("data", "expect_crop"),
    [(_screenshot_bytes(), True), (_photo_bytes(), False)],
    ids=["screenshot", "photo"],
)
async def test_auto_crop(uploaded, data, expect_crop):
    from reverse_image_search_bot.commands.utils import image_to_url

    with patch("reverse_image_search_bot.commands.utils.image_to_bytes", AsyncMock(return_value=(data, "shot1.jpg"))):
        url = await image_to_url(_photo(), auto_crop=True)

    ((filename, size),) = uploaded
    assert url == URL(f"https://u.test/{filename}")
    if expect_crop:
        assert filename == "shot1_crop.jpg"
        assert size == (600, 337)  # the clip inside the tweet, not the whole phone screen
    else:
        assert filename == "shot1.jpg"
        assert size == Image.open(BytesIO(data)).size


async def test_auto_crop_off_uploads_original(uploaded):
    from reverse_image_search_bot.commands.utils import image_to_url

    data = _screenshot_bytes()
    with patch("reverse_image_search_bot.commands.utils.image_to_bytes", AsyncMock(return_value=(data, "shot1.jpg"))):
        await image_to_url(_photo(), auto_crop=False)

    assert uploaded == [("shot1.jpg", (600, 1286))]
