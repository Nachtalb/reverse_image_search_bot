from typing import TypedDict

from telegram import InlineKeyboardButton
from yarl import URL

__all__ = ["InternalResultData", "ResultData", "MetaData", "InternalProviderData", "ProviderData"]

InternalResultData = dict[str, str | int | URL | None | list[str]]
ResultData = dict[str, str | int | URL]


class MetaData(TypedDict, total=False):
    provider: str
    provider_url: URL
    provided_via: str
    provided_via_url: URL
    thumbnail: URL
    similarity: int | float
    buttons: list[InlineKeyboardButton]
    identifier: str
    thumbnail_identifier: str


InternalProviderData = tuple[InternalResultData, MetaData]
ProviderData = tuple[ResultData, MetaData]
