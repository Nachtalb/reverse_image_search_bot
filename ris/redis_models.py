from dataclasses import dataclass, field
from typing import ClassVar

from ris.redis import RedisDataSet
from ris.search import SEARCH_ENGINES


@dataclass
class UserSettings(RedisDataSet):
    user_id: int
    enabled_engines: set[str] = field(default_factory=lambda: set(SEARCH_ENGINES))
    cache_enabled: bool = True
    broadcast_message_chat_id: int | None = None
    broadcast_message_id: int | None = None
    search_count: int = 0

    __keys__: ClassVar[dict[str, str]] = {
        "enabled_engines": "ris:xs:user:{user_id}:enabled_engines",
        "cache_enabled": "ris:sb:user:{user_id}:cache_enabled",
        "broadcast_message_chat_id": "ris:si:user:{user_id}:broadcast:chat_id",
        "broadcast_message_id": "ris:si:user:{user_id}:broadcast:message_id",
        "search_count": "ris:si:user:{user_id}:search_count",
    }
