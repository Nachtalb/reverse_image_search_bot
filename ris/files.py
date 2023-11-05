from hashlib import md5
from pathlib import Path

from aiogram import Bot
from aiogram.types import PhotoSize

from ris import common


async def prepare(media: PhotoSize, bot: Bot) -> tuple[str, str]:
    file_id: str = md5(media.file_unique_id.encode()).hexdigest()
    file_path = Path("photos") / file_id

    tg_file = await bot.get_file(media.file_id)
    if not tg_file.file_path:
        return file_id, ""

    file_path = file_path.with_suffix(Path(tg_file.file_path).suffix)

    if not await common.s3.file_exists(file_path):
        file_content = await bot.download_file(tg_file.file_path)
        if not file_content:
            return file_id, ""

        await common.s3.upload_file(file_content, file_path)
    return file_id, str(file_path.name)
