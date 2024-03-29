import hashlib
from pathlib import Path
from typing import Generator, Sequence, TypeVar

import imageio
from telegram import Update

T = TypeVar("T")


def chunks(sequence: Sequence[T], size: int) -> Generator[Sequence[T], None, None]:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(sequence), size):
        yield sequence[i : i + size]


def create_short_hash(text: str) -> str:
    """Create a SHA-256 hash of a given text and return a 10-character long string representation of the hash.

    Args:
        text: The text to be hashed.

    Returns:
        A 10-character long string representation of the hash.
    """
    hash_object = hashlib.sha256(text.encode())
    hash_hex = hash_object.hexdigest()

    return hash_hex[:10]


async def download_file(update: Update, downloads_dir: Path) -> Path | None:
    """
    Downloads a file from a Telegram update to a specified location with a filename that includes a hash of the file ID.
    If the downloaded file is a video, it extracts the first frame as an image.

    Args:
        update: A Telegram update object that contains the file to be downloaded.
        downloads_dir: A pathlib.Path object representing the directory where the downloaded file will be saved.

    Returns:
        A pathlib.Path object representing the path to the downloaded file (or the first frame image if the file is
        a video), or None if the update message is empty.
    """
    msg = update.message
    if not msg:
        return None

    unloaded_tg_file = msg.document or msg.video or msg.sticker or msg.photo[-1]
    loaded_tg_file = await unloaded_tg_file.get_file()

    suffix = Path(loaded_tg_file.file_path).suffix  # type: ignore[arg-type]
    file_location = downloads_dir / (create_short_hash(unloaded_tg_file.file_unique_id) + suffix)
    image_location = file_location.with_stem(".jpg")

    if file_location.is_file():
        return file_location
    elif image_location.is_file():
        return image_location

    await loaded_tg_file.download_to_drive(file_location)

    if msg.video or msg.animation or (msg.sticker and msg.sticker.is_video):
        # Extract the first frame of the video as an image
        video_reader = imageio.get_reader(file_location, "ffmpeg")  # type: ignore[arg-type]
        first_frame = video_reader.get_data(0)
        image_location = downloads_dir / (create_short_hash(unloaded_tg_file.file_unique_id) + ".jpg")
        imageio.imwrite(image_location, first_frame)
        file_location.unlink()
        return image_location
    else:
        return file_location
