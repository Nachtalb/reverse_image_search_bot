import hashlib
from pathlib import Path
from typing import Generator, Sequence, TypeVar

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
    """Downloads a file from a Telegram update to a specified location with a filename that includes a hash of the file ID.

    Args:
        update: A Telegram update object that contains the file to be downloaded.
        downloads_dir: A pathlib.Path object representing the directory where the downloaded file will be saved.

    Returns:
        A pathlib.Path object representing the path to the downloaded file.

    """
    if not update.message:
        return

    unloaded_tg_file = update.message.document or update.message.sticker or update.message.photo[-1]
    loaded_tg_file = await unloaded_tg_file.get_file()
    suffix = Path(loaded_tg_file.file_path).suffix  # pyright: ignore[reportGeneralTypeIssues]
    file_location = downloads_dir / (create_short_hash(unloaded_tg_file.file_unique_id) + suffix)

    await loaded_tg_file.download_to_drive(file_location)
    return file_location
