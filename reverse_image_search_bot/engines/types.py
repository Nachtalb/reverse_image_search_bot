from typing import TypedDict

from telegram import InlineKeyboardButton
from yarl import URL

__all__ = ["InternalResultData", "ResultData", "MetaData", "InternalProviderData", "ProviderData"]

InternalResultData = dict[str, str | int | URL | None | list[str] | set[str]]
ResultData = dict[str, str | int | URL | list[str] | set[str]]


class MetaData(TypedDict, total=False):
    provider: str
    provider_url: URL
    errors: list[str]
    provided_via: str
    provided_via_url: URL
    thumbnail: URL | list[URL]
    similarity: int | float
    buttons: list[InlineKeyboardButton]
    identifier: str
    thumbnail_identifier: str


InternalProviderData = tuple[InternalResultData, MetaData]
ProviderData = tuple[ResultData, MetaData]
