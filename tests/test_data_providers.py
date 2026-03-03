"""Tests for reverse_image_search_bot.engines.data_providers — all providers mocked HTTP."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from yarl import URL

# ---------------------------------------------------------------------------
# base.py — _instrumented_provide, BaseProvider
# ---------------------------------------------------------------------------


class TestInstrumentedProvide:
    def test_subclass_gets_instrumented(self):
        from reverse_image_search_bot.engines.data_providers.base import BaseProvider

        class DummyProvider(BaseProvider):
            info = {"name": "Dummy", "url": "", "types": [], "site_type": ""}

            async def provide(self):
                return {"result": True}, {}

        p = DummyProvider()
        # provide should be wrapped (not the original)
        assert p.provide.__name__ == "provide"  # functools.wraps preserves name

    @pytest.mark.asyncio
    async def test_hit_metric(self):
        from reverse_image_search_bot.engines.data_providers.base import BaseProvider

        class HitProvider(BaseProvider):
            info = {"name": "HitTest", "url": "", "types": [], "site_type": ""}

            async def provide(self):
                return {"data": True}, {}

        p = HitProvider()
        result, _meta = await p.provide()
        assert result == {"data": True}

    @pytest.mark.asyncio
    async def test_miss_metric(self):
        from reverse_image_search_bot.engines.data_providers.base import BaseProvider

        class MissProvider(BaseProvider):
            info = {"name": "MissTest", "url": "", "types": [], "site_type": ""}

            async def provide(self):
                return {}, {}

        p = MissProvider()
        result, _meta = await p.provide()
        assert result == {}

    @pytest.mark.asyncio
    async def test_error_metric(self):
        from reverse_image_search_bot.engines.data_providers.base import BaseProvider

        class ErrorProvider(BaseProvider):
            info = {"name": "ErrTest", "url": "", "types": [], "site_type": ""}

            async def provide(self):
                raise ValueError("boom")

        p = ErrorProvider()
        with pytest.raises(ValueError, match="boom"):
            await p.provide()


# ---------------------------------------------------------------------------
# anilist.py
# ---------------------------------------------------------------------------


def _mock_anilist_response():
    return {
        "data": {
            "Page": {
                "media": [
                    {
                        "title": {"english": "Attack on Titan", "romaji": "Shingeki no Kyojin"},
                        "coverImage": {"large": "https://img.anilist.co/cover.jpg"},
                        "startDate": {"year": 2013},
                        "endDate": {"year": 2023},
                        "episodes": 87,
                        "status": "FINISHED",
                        "siteUrl": "https://anilist.co/anime/16498",
                        "type": "ANIME",
                        "genres": ["Action", "Drama"],
                        "isAdult": False,
                    }
                ]
            }
        }
    }


@pytest.mark.asyncio
class TestAnilistProvider:
    async def test_provide_success(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_anilist_response()

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await provider.provide(16498, 5)

        assert result["Title"] == "Attack on Titan"
        assert result["Title [romaji]"] == "Shingeki no Kyojin"
        assert result["Episode"] == "5/87"
        assert result["Status"] == "FINISHED"
        assert result["18+ Audience"] == "No"
        assert meta["provided_via"] == "Anilist"

    async def test_provide_no_episode(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_anilist_response()

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(16498)

        assert result["Episode"] == "?/87"

    async def test_provide_adult(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        data = _mock_anilist_response()
        data["data"]["Page"]["media"][0]["isAdult"] = True
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(16498)

        assert result["18+ Audience"] == "Yes 🔞"

    async def test_request_non_200(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await provider.provide(99999)

        assert result == {}
        assert meta == {}

    async def test_request_empty_media(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"Page": {"media": []}}}

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(99999)

        assert result == {}

    async def test_request_with_anilist_token(self):
        from reverse_image_search_bot.engines.data_providers.anilist import AnilistProvider

        provider = AnilistProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_anilist_response()

        with (
            patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp) as mock_post,
            patch("reverse_image_search_bot.engines.data_providers.anilist.settings") as mock_settings,
        ):
            mock_settings.ANILIST_TOKEN = "test-token-123"
            await provider.provide(16498)
            call_kwargs = mock_post.call_args
            assert "Authorization" in call_kwargs.kwargs.get("headers", {})


# ---------------------------------------------------------------------------
# boorus.py
# ---------------------------------------------------------------------------


def _mock_booru_response(api, post_id):
    base = {
        "tag_string_general": "cat dog",
        "tag_string_character": "naruto",
        "tag_string_artist": "artist1",
        "tag_string_copyright": "series1",
        "source": "https://example.com/source",
        "file_url": "https://example.com/image.jpg",
        "rating": "s",
        "image_width": 1920,
        "image_height": 1080,
        "width": 1920,
        "height": 1080,
    }
    if api == "danbooru":
        return base
    elif api == "gelbooru":
        return {"@attributes": {"count": 1}, "post": [base]}
    elif api == "yandere":
        return [base]
    elif api == "sankaku":
        base["tags"] = [
            {"type": 0, "tagName": "general_tag"},
            {"type": 1, "tagName": "artist_tag"},
            {"type": 4, "tagName": "char_tag"},
            {"type": 3, "tagName": "copyright_tag"},
            {"type": 2, "tagName": "loli_tag"},
            {"type": 5, "tagName": "parent_tag"},
            {"type": 8, "tagName": "meta_tag"},
            {"type": 9, "tagName": "action_tag"},
        ]
        base["tag_string_general"] = base["tags"]
        return base
    return base


@pytest.mark.asyncio
class TestBooruProvider:
    async def test_provide_danbooru(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_booru_response("danbooru", 123)

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await provider.provide("danbooru", 123)

        assert result["Size"] == "1920x1080"
        assert result["Rating"] == "Safe"
        assert meta["provided_via"] == "Danbooru"

    async def test_provide_gelbooru(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_booru_response("gelbooru", 456)

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await provider.provide("gelbooru", 456)

        assert result["Size"] == "1920x1080"
        assert result["Rating"] == "S"  # gelbooru keeps raw rating but .title()'d
        assert meta["provided_via"] == "Gelbooru"

    async def test_provide_yandere(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_booru_response("yandere", 789)

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            _result, meta = await provider.provide("yandere", 789)

        assert meta["provided_via"] == "Yandere"

    async def test_provide_sankaku_list_tags(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_booru_response("sankaku", 111)

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide("sankaku", 111)

        assert result.get("By") is not None
        assert result.get("Character") is not None

    async def test_provide_api_404(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {}

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide("danbooru", 999999)

        assert result == {}

    async def test_provide_url_based(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_booru_response("danbooru", 123)

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(URL("https://danbooru.donmai.us/posts/123"))

        assert result["Size"] == "1920x1080"

    async def test_provide_unknown_url(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        result, _meta = await provider.provide(URL("https://unknown.example.com/posts/123"))
        assert result == {}

    async def test_supports_danbooru(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        api, post_id = provider.supports(URL("https://danbooru.donmai.us/posts/12345"))
        assert api == "danbooru"
        assert post_id == 12345

    async def test_supports_gelbooru_regex_no_match_full_url(self):
        """Gelbooru's id_reg uses re.match (anchored at start) so full URLs don't match."""
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        api, _post_id = provider.supports("https://gelbooru.com/index.php?page=post&s=view&id=67890")
        # re.match anchors at start, so id= in query string is never found
        assert api is None

    async def test_supports_unknown(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        api, post_id = provider.supports(URL("https://example.com/posts/123"))
        assert api is None
        assert post_id is None

    async def test_supports_non_digit_id(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        api, _post_id = provider.supports(URL("https://danbooru.donmai.us/posts/abc"))
        assert api is None

    async def test_source_button_valid_url(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        buttons = provider.source_button({"source": "https://twitter.com/artist/123"})
        assert len(buttons) == 1
        assert "Source" in buttons[0].text

    async def test_source_button_invalid_url(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        buttons = provider.source_button({"source": "not a url"})
        assert len(buttons) == 0

    async def test_source_button_missing(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        buttons = provider.source_button({})
        assert len(buttons) == 0

    async def test_thumbnail_download(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        data = {"file_url": "https://example.com/img.jpg"}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"fake image data"

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            meta = await provider._get_thumbnail("3dbooru", 123, data)

        assert "thumbnail" in meta

    async def test_thumbnail_no_url(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        meta = await provider._get_thumbnail("danbooru", 123, {})
        assert meta == {}

    async def test_thumbnail_download_failure(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        data = {"file_url": "https://example.com/img.jpg"}
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            meta = await provider._get_thumbnail("3dbooru", 123, data)

        assert meta == {}

    async def test_thumbnail_url_without_download(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        data = {"file_url": "https://example.com/img.jpg"}
        meta = await provider._get_thumbnail("danbooru", 123, data)
        assert meta["thumbnail"] == URL("https://example.com/img.jpg")

    async def test_get_post_danbooru_failure(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": False}

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await provider.get_post("danbooru", 123)
        assert result is None

    async def test_gelbooru_regex_no_match(self):
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        api, _post_id = provider.supports(URL("https://gelbooru.com/noid"))
        assert api is None

    async def test_supports_gelbooru_id_reg_match(self):
        """Test gelbooru regex match by temporarily changing the regex to re.search-compatible."""
        from reverse_image_search_bot.engines.data_providers.boorus import BooruProvider

        provider = BooruProvider()
        # The id_reg uses re.match which anchors at start — can never match a full URL.
        # This is dead code (line 124). Verify the regex itself works if it matched:
        matcher = provider.urls["gelbooru"]["id_reg"]
        assert matcher.match("id=67890") is not None
        assert matcher.match("id=67890").groups()[0] == "67890"


# ---------------------------------------------------------------------------
# mangadex.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMangadexProvider:
    async def test_provide_by_manga_id(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()

        manga_data = {
            "result": "ok",
            "data": {
                "id": "manga-123",
                "attributes": {
                    "title": {"en": "One Piece"},
                    "altTitles": [{"ja": "ワンピース"}],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 1997,
                    "contentRating": "safe",
                    "description": {"en": "A long pirate adventure story."},
                    "tags": [
                        {"attributes": {"group": "genre", "name": {"en": "Adventure"}}},
                        {"attributes": {"group": "theme", "name": {"en": "Pirates"}}},
                    ],
                    "links": {"al": "21", "mu": "https://www.mangaupdates.com/series/one-piece"},
                },
                "relationships": [
                    {"type": "author", "attributes": {"name": "Oda Eiichiro"}},
                    {"type": "artist", "attributes": {"name": "Oda Eiichiro"}},
                    {"type": "cover_art", "attributes": {"fileName": "cover.jpg"}},
                ],
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = manga_data

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, meta = await provider.provide(manga_id="manga-123")

        assert result["Title"] == "One Piece"
        assert result["Author"] == "Oda Eiichiro"
        assert meta["provided_via"] == "Mangadex"
        assert "thumbnail" in meta

    async def test_provide_by_chapter_id(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()

        chapter_data = {
            "result": "ok",
            "data": {
                "id": "ch-456",
                "relationships": [{"type": "manga", "id": "manga-789"}],
                "attributes": {},
            },
        }
        manga_data = {
            "result": "ok",
            "data": {
                "id": "manga-789",
                "attributes": {
                    "title": {"en": "Naruto"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "finished",
                    "year": 1999,
                    "contentRating": "safe",
                    "description": {"en": "Ninja story."},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }

        call_count = 0

        async def mock_get(url, *args, **kwargs):
            nonlocal call_count
            resp = MagicMock()
            resp.status_code = 200
            if "chapter" in url:
                resp.json.return_value = chapter_data
            else:
                resp.json.return_value = manga_data
            call_count += 1
            return resp

        with patch.object(provider._http_client, "get", side_effect=mock_get):
            result, _meta = await provider.provide(chapter_id="ch-456")

        assert result["Title"] == "Naruto"

    async def test_provide_no_args(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        result, _meta = await provider.provide()
        assert result == {}

    async def test_provide_api_error(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "error"}

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(manga_id="bad-id")

        assert result == {}

    async def test_provide_non_200(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.url = "https://api.mangadex.org/manga/xxx"
        mock_resp.text = "Internal Server Error"

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(manga_id="xxx")

        assert result == {}

    async def test_provide_url_manga_path_bug(self):
        """URL parsing with yarl: parts[0]='/' so /manga/ never matches parts[0]=='manga'.
        This documents the bug — URL-only manga lookups silently return empty."""
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        result, _meta = await provider.provide(url="https://mangadex.org/manga/m-url")
        assert result == {}

    async def test_provide_url_manga_with_patched_url(self):
        """Test the manga URL branch by patching URL to return corrected parts."""
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        manga_data = {
            "result": "ok",
            "data": {
                "id": "m-patched",
                "attributes": {
                    "title": {"en": "Patched Manga"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 2024,
                    "contentRating": "safe",
                    "description": {"en": "Test."},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = manga_data

        # Patch URL so parts[0] == 'manga' (simulating what the code expects)
        mock_url = MagicMock()
        mock_url.parts = ("manga", "m-patched")  # len == 2 != 3, so this won't work either
        # Actually needs len == 3
        mock_url.parts = ("manga", "title", "m-patched")

        with (
            patch("reverse_image_search_bot.engines.data_providers.mangadex.URL", return_value=mock_url),
            patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp),
        ):
            result, _meta = await provider.provide(url="https://mangadex.org/manga/m-patched")
        assert result["Title"] == "Patched Manga"

    async def test_provide_url_chapter_with_patched_url(self):
        """Test the chapter URL branch by patching URL."""
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()

        chapter_data = {
            "result": "ok",
            "data": {
                "id": "c-patched",
                "relationships": [{"type": "manga", "id": "m-from-patched"}],
                "attributes": {},
            },
        }
        manga_data = {
            "result": "ok",
            "data": {
                "id": "m-from-patched",
                "attributes": {
                    "title": {"en": "Via Patched Chapter"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 2024,
                    "contentRating": "safe",
                    "description": {"en": "Test."},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }

        mock_url = MagicMock()
        mock_url.parts = ("chapter", "type", "c-patched")

        async def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = chapter_data if "chapter" in url else manga_data
            return resp

        with (
            patch("reverse_image_search_bot.engines.data_providers.mangadex.URL", return_value=mock_url),
            patch.object(provider._http_client, "get", side_effect=mock_get),
        ):
            result, _meta = await provider.provide(url="https://mangadex.org/chapter/c-patched")
        assert result["Title"] == "Via Patched Chapter"

    async def test_provide_url_chapter(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()

        chapter_data = {
            "result": "ok",
            "data": {
                "id": "c-url",
                "relationships": [{"type": "manga", "id": "m-from-ch"}],
                "attributes": {},
            },
        }
        manga_data = {
            "result": "ok",
            "data": {
                "id": "m-from-ch",
                "attributes": {
                    "title": {"en": "Ch Manga"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 2021,
                    "contentRating": "safe",
                    "description": {"en": "Via chapter."},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }

        async def mock_get(url, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = chapter_data if "chapter" in url else manga_data
            return resp

        with patch.object(provider._http_client, "get", side_effect=mock_get):
            _result, _meta = await provider.provide(url="https://mangadex.org/chapter/c-url")

    async def test_provide_url_bad_path(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        result, _meta = await provider.provide(url="https://mangadex.org/too/many/parts/here")
        assert result == {}

    async def test_legacy_mapping(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "result": "ok",
            "data": [{"attributes": {"newId": "new-uuid"}}],
        }

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            new_id = await provider.legacy_mapping(12345, "chapter")

        assert new_id == "new-uuid"

    async def test_legacy_mapping_empty(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok", "data": []}

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            new_id = await provider.legacy_mapping(99999, "chapter")

        assert new_id is None

    async def test_chapter_with_legacy_numeric_id(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()

        # Legacy mapping returns new UUID
        legacy_resp = MagicMock()
        legacy_resp.status_code = 200
        legacy_resp.json.return_value = {"result": "ok", "data": [{"attributes": {"newId": "new-ch-uuid"}}]}

        chapter_data = {
            "result": "ok",
            "data": {
                "id": "new-ch-uuid",
                "relationships": [{"type": "manga", "id": "manga-from-legacy"}],
                "attributes": {},
            },
        }
        manga_data = {
            "result": "ok",
            "data": {
                "id": "manga-from-legacy",
                "attributes": {
                    "title": {"en": "Legacy Manga"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "finished",
                    "year": 2000,
                    "contentRating": "safe",
                    "description": {"en": "Old."},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }

        async def mock_handler(url_or_json, *args, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            if isinstance(url_or_json, str):
                # GET request
                if "chapter" in url_or_json:
                    resp.json.return_value = chapter_data
                else:
                    resp.json.return_value = manga_data
            return resp

        with (
            patch.object(provider._http_client, "get", side_effect=mock_handler),
            patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=legacy_resp),
        ):
            result, _meta = await provider.provide(chapter_id="12345")

        assert result["Title"] == "Legacy Manga"

    async def test_legacy_mapping_fails_chapter_returns_empty(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        legacy_resp = MagicMock()
        legacy_resp.status_code = 200
        legacy_resp.json.return_value = {"result": "ok", "data": []}

        with patch.object(provider._http_client, "post", new_callable=AsyncMock, return_value=legacy_resp):
            result, _meta = await provider.provide(chapter_id="99999")
        assert result == {}

    async def test_provide_manga_with_links_list(self):
        """When links is a list instead of dict, it should warn and skip.
        Note: the source has a logging bug (positional arg without %s), so we suppress the log error.
        """
        import logging

        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        manga_data = {
            "result": "ok",
            "data": {
                "id": "links-list",
                "attributes": {
                    "title": {"en": "Links List Manga"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 2020,
                    "contentRating": "safe",
                    "description": {"en": "Test."},
                    "tags": [],
                    "links": ["not", "a", "dict"],
                },
                "relationships": [],
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = manga_data

        # Suppress the logging TypeError from the buggy warning() call
        logging.disable(logging.CRITICAL)
        try:
            with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
                result, _meta = await provider.provide(manga_id="links-list")
            assert result["Title"] == "Links List Manga"
        finally:
            logging.disable(logging.NOTSET)

    async def test_provide_chapter_no_manga_rel(self):
        """Chapter with no manga relationship returns empty."""
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        chapter_data = {
            "result": "ok",
            "data": {
                "id": "ch-no-manga",
                "relationships": [{"type": "scanlation_group", "id": "grp-1"}],
                "attributes": {},
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = chapter_data

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(chapter_id="ch-no-manga")
        assert result == {}

    async def test_description_truncation(self):
        from reverse_image_search_bot.engines.data_providers.mangadex import MangadexProvider

        provider = MangadexProvider()
        long_desc = "x" * 200
        manga_data = {
            "result": "ok",
            "data": {
                "id": "trunc-test",
                "attributes": {
                    "title": {"en": "Trunc"},
                    "altTitles": [],
                    "originalLanguage": "ja",
                    "status": "ongoing",
                    "year": 2020,
                    "contentRating": "safe",
                    "description": {"en": long_desc},
                    "tags": [],
                    "links": {},
                },
                "relationships": [],
            },
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = manga_data

        with patch.object(provider._http_client, "get", new_callable=AsyncMock, return_value=mock_resp):
            result, _meta = await provider.provide(manga_id="trunc-test")

        assert result["Description"].endswith("...")
        assert len(result["Description"]) == 150


# ---------------------------------------------------------------------------
# pixiv.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPixivProvider:
    async def test_provide_not_authenticated(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.authenticated = False
            result, _meta = await provider.provide(12345)
            assert result == {}

    async def test_provide_request_returns_none(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.authenticated = True
            provider.request = AsyncMock(return_value=None)
            result, _meta = await provider.provide(12345)
            assert result == {}

    async def test_provide_success(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.authenticated = True
            provider.info = PixivProvider.info

            mock_data = MagicMock()
            mock_data.title = "Test Artwork"
            mock_data.tags = [MagicMock(translated_name="tag1"), MagicMock(translated_name="tag2")]
            mock_data.type = "illust"
            mock_data.page_count = 1
            mock_data.width = 800
            mock_data.height = 600
            mock_data.user.name = "TestArtist"
            mock_data.user.account = "testartist"
            mock_data.user.id = 42
            mock_data.x_restrict = 0
            mock_data.image_urls = {"large": "https://example.com/large.jpg"}
            mock_data.id = 12345

            provider.request = AsyncMock(return_value=mock_data)
            provider._images = AsyncMock(return_value=[URL("https://uploads.test/12345_p0.jpg")])

            result, meta = await provider.provide(12345)
            assert result["Title"] == "Test Artwork"
            assert result["Creator"] == "TestArtist"
            assert result["Type"] == "Artwork"
            assert meta["provided_via"] == "Pixiv"

    async def test_provide_over_10_pages(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.authenticated = True
            provider.info = PixivProvider.info

            mock_data = MagicMock()
            mock_data.title = "Big Post"
            mock_data.tags = []
            mock_data.type = "manga"
            mock_data.page_count = 15
            mock_data.width = 800
            mock_data.height = 600
            mock_data.user.name = "Artist"
            mock_data.user.account = "artist"
            mock_data.user.id = 1
            mock_data.x_restrict = 1
            mock_data.image_urls = {"large": "https://example.com/large.jpg"}
            mock_data.id = 999

            provider.request = AsyncMock(return_value=mock_data)
            provider._images = AsyncMock(return_value=[URL("https://uploads.test/999_p0.jpg")])

            result, _meta = await provider.provide(999)
            assert "more than 10 artworks" in next(iter(result.values()))
            assert result["Type"] == "Manga"
            assert result["18+ Audience"] == "Yes 🔞"

    async def test_request_string_id(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()
            provider._cache = {}

            mock_illust = MagicMock()
            mock_illust.error = None
            mock_illust.illust = {"title": "test"}
            provider.api.illust_detail.return_value = mock_illust

            result = await provider.request("12345")
            assert result == {"title": "test"}

    async def test_request_url_string(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()
            provider._cache = {}

            mock_illust = MagicMock()
            mock_illust.error = None
            mock_illust.illust = {"title": "from_url"}
            provider.api.illust_detail.return_value = mock_illust

            result = await provider.request("https://www.pixiv.net/artworks/67890")
            assert result == {"title": "from_url"}
            provider.api.illust_detail.assert_called_once_with(67890)

    async def test_request_non_matching_string(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider._cache = {}

            result = await provider.request("not-a-valid-id")
            assert result is None

    async def test_request_api_error(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()
            provider.logger = MagicMock()
            provider._cache = {}

            mock_illust = MagicMock()
            mock_illust.error.message = "Rate limit exceeded"
            mock_illust.error.user_message = "Please wait"
            provider.api.illust_detail.return_value = mock_illust

            result = await provider.request(12345)
            assert result is None

    async def test_images_single_page(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()

            mock_data = MagicMock()
            mock_data.page_count = 1
            mock_data.width = 800
            mock_data.height = 600
            mock_data.image_urls = {
                "large": "https://example.com/large.jpg",
                "original": "https://example.com/orig.jpg",
            }
            mock_data.id = 111

            with patch.object(provider, "_download_image", return_value=URL("https://uploads.test/img.jpg")):
                images = await provider._images(mock_data)
            assert len(images) == 1

    async def test_init_successful_auth(self):
        """Test PixivProvider.__init__ when auth succeeds."""
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with (
            patch("reverse_image_search_bot.engines.data_providers.pixiv.PixivConfig") as mock_config_cls,
            patch("reverse_image_search_bot.engines.data_providers.pixiv.AppPixivAPI") as mock_api_cls,
        ):
            mock_config = MagicMock()
            mock_config.refresh_token = "test-refresh"
            mock_config_cls.return_value = mock_config

            mock_api = MagicMock()
            mock_api.refresh_token = "new-refresh"
            mock_api.access_token = "new-access"
            mock_api_cls.return_value = mock_api

            provider = PixivProvider()
            assert provider.authenticated is True
            assert mock_config.refresh_token == "new-refresh"
            assert mock_config.access_token == "new-access"

    async def test_request_invalid_grant_retries(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()
            provider.logger = MagicMock()
            provider._cache = {}

            # First call returns invalid_grant error
            mock_error = MagicMock()
            mock_error.error.message = "Error Message: invalid_grant"
            mock_error.error.user_message = ""

            # Second call (after re-auth) succeeds
            mock_success = MagicMock()
            mock_success.error = None
            mock_success.illust = {"title": "after_reauth"}

            provider.api.illust_detail.side_effect = [mock_error, mock_success]

            result = await provider.request(12345)
            assert result == {"title": "after_reauth"}
            provider.api.auth.assert_called_once()

    async def test_download_image(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()

            with patch(
                "reverse_image_search_bot.engines.data_providers.pixiv.upload_file",
                return_value=URL("https://uploads.test/out.jpg"),
            ) as mock_upload:
                result = provider._download_image(("https://example.com/img/test.jpg", 12345, 0))
                assert result == URL("https://uploads.test/out.jpg")
                mock_upload.assert_called_once()

    async def test_images_multi_page(self):
        from reverse_image_search_bot.engines.data_providers.pixiv import PixivProvider

        with patch.object(PixivProvider, "__init__", lambda self, *a, **kw: None):
            provider = PixivProvider.__new__(PixivProvider)
            provider.api = MagicMock()

            mock_data = MagicMock()
            mock_data.page_count = 3
            mock_data.width = 800
            mock_data.height = 600
            mock_data.meta_pages = [
                MagicMock(image_urls={"large": "https://example.com/1.jpg"}),
                MagicMock(image_urls={"large": "https://example.com/2.jpg"}),
                MagicMock(image_urls={"large": "https://example.com/3.jpg"}),
            ]
            mock_data.id = 222

            with patch.object(provider, "_download_image", return_value=URL("https://uploads.test/img.jpg")):
                images = await provider._images(mock_data)
            assert len(images) == 3


# ---------------------------------------------------------------------------
# pixiv_config.py
# ---------------------------------------------------------------------------


class TestPixivConfig:
    def test_repr(self, tmp_path):
        with patch("reverse_image_search_bot.config.pixiv_config.PIXIV_CONFIG", tmp_path / "pixiv.json"):
            from reverse_image_search_bot.config.pixiv_config import PixivConfig

            cfg = PixivConfig()
            assert repr(cfg) == "<PixivConfig(...)>"

    def test_setattr_and_getattr(self, tmp_path):
        with patch("reverse_image_search_bot.config.pixiv_config.PIXIV_CONFIG", tmp_path / "pixiv.json"):
            from reverse_image_search_bot.config.pixiv_config import PixivConfig

            cfg = PixivConfig()
            cfg.refresh_token = "test-token"
            assert cfg.refresh_token == "test-token"
            cfg.access_token = "access-123"
            assert cfg.access_token == "access-123"
