import validators
from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import fix_url, safe_get, tagify, url_button

from .base import BaseProvider, provider_cache


class MangadexProvider(BaseProvider):
    info = {"name": "Mangadex", "url": "https://mangadex.org/", "types": ["Manga"], "site_type": "Manga DB & Reader"}
    api_base = URL("https://api.mangadex.org/")

    def _request(
        self, endpoint: str, params: dict = {}, json: dict = {}, method: str = "get", **kwargs
    ) -> dict | list | None:
        request_method = getattr(self.session, method.lower())
        if not request_method:
            return

        url = self.api_base / endpoint
        response = request_method(str(url), params=params, json=json, **kwargs)

        if response.status_code != 200:
            self.logger.error('Mangadex API error: "%s" -- %s', response.url, response.text)
            return

        data = response.json()
        if data["result"] == "error":
            return
        return data["data"]

    def legacy_mapping(self, id: int, kind: str) -> str | None:
        data = self._request("legacy/mapping", json={"type": kind, "ids": [id]}, method="POST")
        if not isinstance(data, list) or not data:
            return
        return safe_get(data, "[0].attributes.newId")

    @provider_cache
    def chapter(self, chapter_id: str) -> dict | None:
        if chapter_id.isdigit():
            chapter_id = self.legacy_mapping(int(chapter_id), "chapter")  # type: ignore
            if not chapter_id:
                return
        return self._request(f"chapter/{chapter_id}")  # type: ignore

    @provider_cache
    def manga(self, manga_id: str) -> dict | None:
        return self._request(f"manga/{manga_id}", {"includes[]": ["artist", "cover_art", "author"]})  # type: ignore

    def provide(self, url: str | URL = None, chapter_id: str = None, manga_id: str = None) -> InternalProviderData:
        chapter_id = str(chapter_id) if chapter_id else None
        manga_id = str(manga_id) if manga_id else None
        if not url and not chapter_id and not manga_id:
            return {}, {}
        elif url and (url := URL(url)):
            if len(url.parts) != 3:  # ('/', 'chapter' | 'manga', '...')
                return {}, {}
            elif url.parts[0] == "manga":
                manga_id = url.parts[-1]
            elif url.parts[0] == "chapter":
                chapter_id = url.parts[-1]
        if not chapter_id and not manga_id:
            return {}, {}

        chapter_data = self.chapter(chapter_id) if chapter_id else {}
        chapter_data = chapter_data or {}
        chapter_id = chapter_data.get("id", "")

        manga_data = {}
        if chapter_data:
            if manga_rel := next(iter(filter(lambda rel: rel["type"] == "manga", chapter_data["relationships"])), None):
                manga_id = manga_rel["id"]

        if not manga_id:
            return {}, {}

        manga_data = self.manga(manga_id) or {}

        if not manga_data:
            return {}, {}

        result = {
            "Title": safe_get(manga_data, "attributes.title.en"),
            "Title [ja]": safe_get(manga_data, "attributes.altTitles.[ja].ja"),
            "Original Language": safe_get(manga_data, "attributes.originalLanguage"),
            "Status": safe_get(manga_data, "attributes.status", "").title(),
            "Year": safe_get(manga_data, "attributes.year"),
            "Rating": safe_get(manga_data, "attributes.contentRating", "").title(),
            "Description": safe_get(manga_data, "attributes.description.en"),
            "Author": safe_get(manga_data, "relationships.[type=author].attributes.name"),
            "Artist": safe_get(manga_data, "relationships[type=artist].attributes.name"),
        }

        if desc := result.get("Description"):
            result["Description"] = desc[:147] + "..."

        tags = {}
        for tag in safe_get(manga_data, "attributes.tags", []):
            tag_type = safe_get(tag, "attributes.group")
            tags.setdefault(tag_type, [])
            tags[tag_type].append(safe_get(tag, "attributes.name.en"))
        for tag_type, raw_tags in tags.items():
            if usable_tags := tagify(raw_tags):
                result[tag_type.title()] = ", ".join(usable_tags)

        buttons = [
            url_button("https://mangadex.org/title/" + manga_id, text="Mangadex"),
        ]
        if chapter_id:
            buttons.append(url_button(f"https://mangadex.org/chapter/{chapter_id}", text="Chapter"))

        links = safe_get(manga_data, "attributes.links", {})
        if isinstance(links, list) and links:
            self.logger.warning("Found a manga with link list", manga_id)
        if isinstance(links, dict):
            for key, url in safe_get(manga_data, "attributes.links", {}).items():
                if not validators.url(url):  # type: ignore
                    url = fix_url(f"{key}:manga:{url}")
                else:
                    url = URL(url)  # type: ignore
                buttons.append(url_button(url))

        meta: MetaData = {
            "provided_via": self.info["name"],
            "provided_via_url": URL(self.info["url"]),
            "buttons": buttons,
            "identifier": manga_id,
        }

        if cover := safe_get(manga_data, "relationships.[type=cover_art].attributes.fileName"):
            cover: str
            meta.update(
                {
                    "thumbnail": URL(f"https://uploads.mangadex.org/covers/{manga_id}/{cover}"),
                    "thumbnail_identifier": cover,
                }
            )

        return result, meta
