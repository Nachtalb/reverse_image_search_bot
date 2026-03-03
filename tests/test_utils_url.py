"""Tests for reverse_image_search_bot.utils.url — fix_url and url_icon."""

import pytest
from yarl import URL

from reverse_image_search_bot.utils.url import fix_url, url_icon


class TestFixUrl:
    def test_normal_url_passthrough(self):
        url = "https://example.com/image.jpg"
        assert fix_url(url) == URL(url)

    def test_anilist_shorthand(self):
        assert fix_url("al:anime:12345") == URL("https://anilist.co/anime/12345")

    def test_anilist_with_category(self):
        assert fix_url("al:manga:12345") == URL("https://anilist.co/manga/12345")

    def test_mal_shorthand(self):
        assert fix_url("mal:anime:12345") == URL("https://myanimelist.net/anime/12345")

    def test_mal_manga(self):
        assert fix_url("mal:manga:12345") == URL("https://myanimelist.net/manga/12345")

    def test_mangaupdates_shorthand(self):
        assert fix_url("mu:series:12345") == URL("https://www.mangaupdates.com/series.html?id=12345")

    def test_novelupdates_shorthand(self):
        assert fix_url("nu:series:my-novel") == URL("https://www.novelupdates.com/series/my-novel")

    def test_bookwalker_shorthand(self):
        assert fix_url("bw:book:12345") == URL("https://bookwalker.jp/12345")

    def test_kitsu_numeric(self):
        assert fix_url("kt:manga:12345") == URL("https://kitsu.io/api/edge/manga/12345")

    def test_kitsu_slug(self):
        assert fix_url("kt:manga:my-manga") == URL("https://kitsu.io/api/edge/manga?filter[slug]=my-manga")

    def test_animeplanet_shorthand(self):
        assert fix_url("ap:anime:my-anime") == URL("https://www.anime-planet.com/anime/my-anime")

    def test_empty_middle_not_matched(self):
        """Shorthand with empty middle segment (e.g. 'al::12345') doesn't match the regex."""
        # These pass through as-is (yarl URL)
        result = fix_url("al::12345")
        assert result == URL("al::12345")

    def test_pixiv_image_url(self):
        url = "https://i.pximg.net/img-original/img/2024/01/01/00/00/00/12345678_p0.jpg"
        result = fix_url(url)
        assert result == URL("https://www.pixiv.net/artworks/12345678")

    def test_unknown_shorthand_raises(self):
        with pytest.raises(KeyError):
            fix_url("unknown:cat:123")

    def test_yarl_url_passthrough(self):
        url = URL("https://example.com")
        assert fix_url(url) == url


class TestUrlIcon:
    def test_twitter(self):
        result = url_icon("https://twitter.com/user")
        assert "Twitter" in result

    def test_pixiv(self):
        result = url_icon("https://www.pixiv.net/artworks/123")
        assert "Pixiv" in result

    def test_danbooru(self):
        result = url_icon("https://danbooru.donmai.us/posts/123")
        assert "Danbooru" in result

    def test_anilist_anime(self):
        result = url_icon("https://anilist.co/anime/123")
        assert "AniList" in result

    def test_anilist_character(self):
        result = url_icon("https://anilist.co/character/123")
        assert "AniList Character" in result

    def test_anilist_manga(self):
        result = url_icon("https://anilist.co/manga/123")
        assert "AniList Manga" in result

    def test_myanimelist(self):
        result = url_icon("https://myanimelist.net/anime/123")
        assert "MyAnimeList" in result

    def test_unknown_host(self):
        result = url_icon("https://www.somesite.com/page")
        assert "Somesite" in result

    def test_without_icon(self):
        result = url_icon("https://twitter.com/user", with_icon=False)
        assert "Twitter" in result

    def test_without_text(self):
        result = url_icon("https://twitter.com/user", with_text=False)
        assert "Twitter" not in result

    def test_custom_text(self):
        result = url_icon("https://twitter.com/user", custom_text="Custom")
        assert "Custom" in result

    def test_yandere(self):
        result = url_icon("https://yande.re/post/show/123")
        assert "Yandere" in result

    def test_mangaupdates(self):
        result = url_icon("https://www.mangaupdates.com/series/123")
        assert "MangaUpdates" in result

    def test_nicovideo(self):
        result = url_icon("https://www.nicovideo.jp/watch/sm123")
        assert "Nico Nico" in result

    def test_sankaku(self):
        result = url_icon("https://chan.sankakucomplex.com/post/show/123")
        assert "Sankaku Complex" in result

    def test_idol_sankaku(self):
        result = url_icon("https://idol.sankakucomplex.com/post/show/123")
        assert "Idol Sankaku Complex" in result

    def test_seiga_nicovideo(self):
        result = url_icon("https://seiga.nicovideo.jp/seiga/im123")
        assert "Nico Nico Seiga" in result

    def test_bookwalker(self):
        result = url_icon("https://www.bookwalker.jp/de123")
        assert "Book Walker" in result

    def test_behoimi(self):
        result = url_icon("https://behoimi.org/post/show/123")
        assert "3D Booru" in result

    def test_novelupdates(self):
        result = url_icon("https://www.novelupdates.com/series/test")
        assert "NovelUpdates" in result
