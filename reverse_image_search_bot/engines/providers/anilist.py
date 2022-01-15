from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import anilist_info, tagify, url_button


class AnilistProvider:
    def _anilist_provider(self, anilist_id: int, episode_at: int | str = None) -> InternalProviderData:
        ani_data = anilist_info(anilist_id)
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
            "provided_via": "AniList",
            "provided_via_url": URL("https://anilist.co/"),
            "thumbnail": URL(ani_data["coverImage"]["large"]),
            "buttons": [url_button(ani_data["siteUrl"])],
            "identifier": ani_data["siteUrl"],
            "thumbnail_identifier": ani_data["coverImage"]["large"],
        }

        return result, meta
