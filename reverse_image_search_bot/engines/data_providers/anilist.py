from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import tagify, url_button

from .base import BaseProvider, provider_cache


class AnilistProvider(BaseProvider):
    info = {
        "name": "Anilist",
        "url": "https://anilist.co/",
        "types": ["Anime", "Manga"],
        "site_type": "Anime & Manga DB",
    }

    api_base = URL("https://graphql.anilist.co")

    @provider_cache
    def request(self, anilist_id: int) -> dict | None:
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

        payload = {"query": query, "variables": {"id": anilist_id}}
        response = self.session.post(str(self.api_base), json=payload)
        if response.status_code != 200:
            return

        return next(iter(response.json()["data"]["Page"]["media"]), None)

    def provide(self, anilist_id: int, episode_at: int | str = None) -> InternalProviderData:
        ani_data = self.request(anilist_id)
        if not ani_data:
            return {}, {}

        episode_at = "?" if episode_at is None else episode_at

        result = {
            "Title": ani_data["title"]["english"],
            "Title [romaji]": ani_data["title"]["romaji"],
            "Episode": f'{episode_at}/{ani_data["episodes"]}',
            "Status": ani_data["status"],
            "Type": ani_data["type"],
            "Year": f"{ani_data['startDate']['year']}-{ani_data['endDate']['year']}",
            "Genres": tagify(ani_data["genres"]),
            "18+ Audience": "Yes 🔞" if ani_data["isAdult"] else "No",
        }

        meta: MetaData = {
            "provided_via": self.info["name"],
            "provided_via_url": URL(self.info["url"]),
            "thumbnail": URL(ani_data["coverImage"]["large"]),
            "buttons": [url_button(ani_data["siteUrl"])],
            "identifier": ani_data["siteUrl"],
            "thumbnail_identifier": ani_data["coverImage"]["large"],
        }

        return result, meta
