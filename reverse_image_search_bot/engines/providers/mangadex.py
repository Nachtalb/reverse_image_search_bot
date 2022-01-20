import validators
from yarl import URL

from reverse_image_search_bot.engines.types import InternalProviderData, MetaData
from reverse_image_search_bot.utils import fix_url, safe_get, tagify, url_button
from reverse_image_search_bot.utils.api import mangadex_chapter, mangadex_manga


class MangadexProvider:
    provider_name = "Mangadex"
    provider_url = URL("https://mangadex.org/")
    provides = ["Manga"]

    def _mangadex_provider(
        self, url: str | URL = None, chapter_id: str = None, manga_id: str = None
    ) -> InternalProviderData:
        chapter_id = str(chapter_id)
        manga_id = str(manga_id)
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

        chapter_data = mangadex_chapter(chapter_id) if chapter_id else {}
        chapter_data = chapter_data or {}
        chapter_id = chapter_data.get('id', '')

        manga_data = {}
        if chapter_data:
            if manga_rel := next(iter(filter(lambda rel: rel["type"] == "manga", chapter_data["relationships"])), None):
                manga_id = manga_rel["id"]

        if not manga_id:
            return {}, {}

        manga_data = mangadex_manga(manga_id) or {}

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

        for key, url in safe_get(manga_data, "attributes.links", {}).items():
            if not validators.url(url):  # type: ignore
                url = fix_url(f"{key}:manga:{url}")
            else:
                url = URL(url)  # type: ignore
            buttons.append(url_button(url))

        meta: MetaData = {
            "provided_via": "Mangadex",
            "provided_via_url": URL("https://mangadex.org/"),
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
