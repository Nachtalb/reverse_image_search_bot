import re

from emoji import emojize
from telegram import InlineKeyboardButton
import validators
from yarl import URL


def fix_url(url: URL | str) -> URL:
    if not validators.url(str(url)) and (match := re.match("((?!:).+):((?!:).*):(.*)", str(url))):  # type: ignore
        short, category, id = match.groups()
        match short:
            case "al" | "anilist":
                category = category or "anime"
                return URL(f"https://anilist.co/{category}/{id}")
            case "ap" | "animeplanet":
                category = "anime"
                return URL(f"https://www.anime-planet.com/{category}/{id}")
            case "bw" | "bookwalker.jp":
                return URL(f"https://bookwalker.jp/{id}")
            case "mu" | "mangaupdates":
                return URL(f"https://www.mangaupdates.com/series.html?id={id}")
            case "nu" | "novelupdates":
                return URL(f"https://www.novelupdates.com/series/{id}")
            case "kt" | "kitsu":
                if id.isdigit():
                    return URL(f"https://kitsu.io/api/edge/manga/{id}")
                return URL(f"https://kitsu.io/api/edge/manga?filter[slug]={id}")
            case "mal" | "myanimelist":
                category = category or "anime"
                return URL(f"https://myanimelist.net/{category}/{id}")
            case _:
                raise KeyError()

    url = URL(url)

    match url.host:
        case "i.pximg.net":
            art_id_match = re.match(r"^\d+", next(reversed(url.parts)))
            if art_id_match:
                art_id = art_id_match[0]
                return URL("https://www.pixiv.net/artworks/" + art_id)

    return url


def url_icon(url: URL | str, with_icon: bool = True, with_text: bool = True, custom_text: str = None) -> str:
    url = URL(url)

    icon = ":globe_with_meridians:"
    match url.host:
        case "twitter.com":
            text = "Twitter"
            icon = ":bird:"
        case "www.pixiv.net" | "pixiv.net" | "i.pximg.net":
            text = "Pixiv"
            icon = ":P_button:"
        case "danbooru.donmai.us":
            text = "Danbooru"
            icon = ":package:"
        case "yande.re":
            text = "Yandere"
        case "myanimelist.net":
            text = "MyAnimeList"
        case "www.mangaupdates.com" | "mangaupdates.com":
            text = "MangaUpdates"
        case "www.novelupdates.com" | "novelupdates.com":
            text = "NovelUpdates"
        case "www.nicovideo.jp" | "nicovideo.jp":
            text = "Nico Nico"
        case "seiga.nicovideo.jp":
            text = "Nico Nico Seiga"
        case "www.bookwalker.jp" | "bookwalker.jp":
            text = "Book Walker"
        case "behoimi.org":
            text = "3D Booru"
        case "chan.sankakucomplex.com" | "c1.sankakucomplex.com" | "sankakucomplex.com":
            text = "Sankaku Complex"
        case "idol.sankakucomplex.com":
            text = "Idol Sankaku Complex"
        case _:
            text = url.host.split(".")[-2].replace('_', ' ').replace('-', ' ').title()  # type: ignore

    if custom_text:
        text = custom_text
    if not with_text:
        text = ""
    if not with_icon:
        icon = ""
    return emojize(f"{icon} {text}", language="alias")


def url_button(
    url: URL | str, with_icon: bool = True, with_text: bool = True, fix_url_: bool = True, text: str = None
) -> InlineKeyboardButton:
    if fix_url_:
        url = fix_url(url)
    return InlineKeyboardButton(text=url_icon(url, with_icon, with_text, text), url=str(url))
