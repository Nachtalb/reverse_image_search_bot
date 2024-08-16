import re

from yarl import URL

from .types import Info, Source


def tagify(tag: str) -> str | None:
    normed = re.sub(r"[^\w_ ]", "", tag)
    temp = re.sub(r"[_ ]", "", normed)
    if not normed or len(temp) < 4:
        return None

    if normed[0].isdigit():
        return None

    return normed.replace(" ", "_")


def format_info(info: Info) -> str:
    title = f"<b>{info.title}</b>"
    text = str(info.description)

    if not text:
        tags = info.tags
        if info.maxed:
            tags = tags[:5]

        tags = list(filter(None, map(tagify, tags)))

        text = "#" + ", #".join(tags)

    if info.wrap_pre:
        text = f"<pre>{text}</pre>"
    elif info.wrap_code:
        text = f"<code>{text}</code>"

    if info.url:
        text = f'<a href="{info.url}">{text}</a>'

    return f"{title}: {text}"


def format_link(link: str) -> str | None:
    url = URL(link)
    return url.host


def format_source(source: Source) -> tuple[str, list[str | tuple[str, str]], list[tuple[str, str]]]:
    engine = source.engine_data["engine"]
    platform = source.platform

    title = f"Provided by: {engine.capitalize()} ({platform.capitalize()})"
    texts = [format_info(info) for info in source.additional_info]
    text = f"{title}\n\n" + "\n".join(texts)

    return (
        text,
        source.source_links,
        [(host, link) for link in source.additional_links if (host := format_link(link))],
    )
