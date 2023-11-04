from hashlib import md5
from pathlib import Path

from aiogram import Bot
from aiogram.types import PhotoSize

from ris.s3 import S3Manager


async def prepare(media: PhotoSize, bot: Bot, s3: S3Manager) -> str:
    file_path = Path("photos") / md5(media.file_unique_id.encode()).hexdigest()

    tg_file = await bot.get_file(media.file_id)
    if not tg_file.file_path:
        return ""

    file_path = file_path.with_suffix(Path(tg_file.file_path).suffix)

    if not await s3.file_exists(file_path):
        file_content = await bot.download_file(tg_file.file_path)
        if not file_content:
            return ""

        await s3.upload_file(file_content, file_path)
    return str(file_path.name)
