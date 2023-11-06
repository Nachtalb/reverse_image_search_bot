from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import ClientSession
    from redis.asyncio import Redis

    from ris.redis import RedisStorage
    from ris.s3 import S3Manager

redis: "Redis" = None  # type: ignore[assignment]
http_session: "ClientSession" = None  # type: ignore[assignment]
s3: "S3Manager" = None  # type: ignore[assignment]
redis_storage: "RedisStorage" = None  # type: ignore[assignment]

USER_AGENT = "reverse_image_search_bot/3.0"
LEGIT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    " Edg/119.0.0.0"
)

LINK_MAP = {
    "saucenao": '<a href="https://saucenao.com">SauceNAO</a>',
    "iqdb": '<a href="https://iqdb.org">IQDB</a>',
    "zerochan": '<a href="https://www.zerochan.net">Zerochan</a>',
    "3dbooru": '<a href="http://behoimi.org">3dbooru</a>',
    "e_shuushuu": '<a href="https://e-shuushuu.net">e-shuushuu</a>',
    "ascii2d": '<a href="https://ascii2d.net">ASCII2D</a>',
    "trace.moe": '<a href="https://trace.moe">TraceMoe</a>',
    "danbooru": '<a href="https://danbooru.donmai.us">Danbooru</a>',
    "gelbooru": '<a href="https://gelbooru.com">Gelbooru</a>',
    "yandere": '<a href="https://yande.re">Yandere</a>',
    "konachan": '<a href="https://konachan.com">Konachan</a>',
    "sankaku": '<a href="https://chan.sankakucomplex.com">Sankaku</a>',
    "pixiv": '<a href="https://www.pixiv.net">Pixiv</a>',
}
