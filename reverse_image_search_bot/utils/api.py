from functools import partial
import json
from logging import getLogger

from cachetools import TTLCache, cached
from cachetools.keys import hashkey
from requests import Session

DataAPICache = TTLCache(maxsize=1e4, ttl=12 * 60 * 60)

logger = getLogger("API")
SESSION = Session()


@cached(DataAPICache)
def anilist_info(anilist_id: int) -> dict | None:
    query = """
query ($id: Int) {
    Page (perPage: 1) {
        media (id: $id) {
            title {
                english
                romaji
            }
            coverImage {
                large
            }
            startDate {
                year
            }
            endDate {
                year
            }
            episodes
            status
            siteUrl
            type
            genres
            isAdult
        }
    }
}
    """.strip()

    payload = json.dumps({"query": query, "variables": {"id": anilist_id}})

    response = SESSION.post("https://graphql.anilist.co", data=payload, headers={"Content-Type": "application/json"})
    if response.status_code != 200:
        return

    return next(iter(response.json()["data"]["Page"]["media"]), None)


@cached(DataAPICache)
def danbooru_info(danbooru_id: int) -> dict | None:
    response = SESSION.get(
        f"https://danbooru.donmai.us/posts/{danbooru_id}.json", headers={"Content-Type": "application/json"}
    )

    if response.status_code != 200 or response.json().get("success") is False:
        return

    return response.json()


@cached(DataAPICache)
def yandere_info(yandere_id: int) -> dict | None:
    response = SESSION.get(
        f"https://yande.re/post.json?tags=id:{yandere_id}", headers={"Content-Type": "application/json"}
    )

    if response.status_code == 200 and (post := next(iter(response.json()), None)):
        return post


@cached(DataAPICache)
def gelbooru_info(gelbooru_id: int) -> dict | None:
    response = SESSION.get(
        f"https://gelbooru.com/index.php?page=dapi&s=post&q=index&json=1&id={gelbooru_id}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code != 200 or response.json().get("@attributes", {}).get("count", 0) == 0:
        return

    return response.json()["post"][0]


def _mangadex_api(endpoint: str, request_data: dict = {}) -> dict | None:
    response = SESSION.get(endpoint, params=request_data)
    if response.status_code != 200:
        logger.error('Mangadex API error: "%s" -- %s', response.url, response.text)
        return
    data = response.json()
    if data.get("result") == "error":
        return
    return data["data"]


@cached(DataAPICache, key=partial(hashkey, "mangadex_chapter"))
def mangadex_chapter(chapter_id: str) -> dict | None:
    return _mangadex_api(f"https://api.mangadex.org/chapter/{chapter_id}")


@cached(DataAPICache, key=partial(hashkey, "mangadex_manga"))
def mangadex_manga(manga_id: str) -> dict | None:
    return _mangadex_api(
        f"https://api.mangadex.org/manga/{manga_id}", {"includes[]": ["artist", "cover_art", "author"]}
    )
