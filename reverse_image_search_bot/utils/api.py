import json

from cachetools import TTLCache, cached
from requests import Session

DataAPICache = TTLCache(maxsize=1e4, ttl=12 * 60 * 60)

ANILIST_SESSION = Session()


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
        }
    }
}
    """.strip()

    payload = json.dumps({"query": query, "variables": {"id": anilist_id}})

    response = ANILIST_SESSION.post(
        "https://graphql.anilist.co", data=payload, headers={"Content-Type": "application/json"}
    )
    if response.status_code != 200:
        return

    return next(iter(response.json()["data"]["Page"]["media"]), None)


DANBOORU_SESSION = Session()


@cached(DataAPICache)
def danbooru_info(danbooru_id: int) -> dict | None:
    response = DANBOORU_SESSION.get(
        f"https://danbooru.donmai.us/posts/{danbooru_id}.json", headers={"Content-Type": "application/json"}
    )

    if response.status_code != 200 or response.json().get("success") is False:
        return

    return response.json()
