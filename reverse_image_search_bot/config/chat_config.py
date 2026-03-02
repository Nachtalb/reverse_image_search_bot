from reverse_image_search_bot.config.db import load_config, save_field


def single_chat(cls: type[ChatConfig]):
    def get_instance(chat_id: int):
        if not hasattr(cls, "_loaded_chats"):
            cls._loaded_chats = {}

        if chat_id in cls._loaded_chats:
            return cls._loaded_chats[chat_id]
        else:
            instance = cls(chat_id)
            if len(cls._loaded_chats) >= 500:
                oldest_id = next(iter(cls._loaded_chats))
                del cls._loaded_chats[oldest_id]
            cls._loaded_chats[chat_id] = instance
            return instance

    return get_instance


@single_chat
class ChatConfig:
    """Per-chat configuration — keyed by chat_id.

    For private chats, chat_id == user_id, so settings are effectively per-user.
    For group chats, settings apply to the whole group.
    """

    _default_config: dict = {
        "show_buttons": True,  # show engine result buttons at all
        "show_best_match": True,  # show the "Best Match" button
        "show_link": True,  # show the "Go To Image" link button
        "auto_search_enabled": True,  # master autosearch toggle for this chat
        "auto_search_engines": None,  # None = all; list[str] = enabled engine names for autosearch
        "button_engines": None,  # None = all; list[str] = engine names shown as buttons
        "engine_empty_counts": {},  # dict[str, int] consecutive empty result counts per engine
        "onboarded": False,  # whether a group has completed the onboarding flow
        "failures_in_a_row": 0,
    }
    _loaded_chats: dict = {}

    show_buttons: bool
    show_best_match: bool
    show_link: bool
    auto_search_enabled: bool
    auto_search_engines: list | None
    button_engines: list | None
    engine_empty_counts: dict
    onboarded: bool
    failures_in_a_row: int

    def reset_engine_counter(self, engine_name: str):
        """Reset the consecutive-empty counter for an engine (e.g. after re-enabling it)."""
        counts = dict(self.engine_empty_counts)
        counts.pop(engine_name, None)
        self.engine_empty_counts = counts

    def __init__(self, chat_id: int):
        self.chat_id: int = chat_id
        self._config: dict = dict(self._default_config)

        # Groups default to both off until onboarded
        is_new = True
        saved = load_config(chat_id)
        if saved is not None:
            is_new = False
            self._config.update(saved)

        if is_new and chat_id < 0:
            self._config["show_buttons"] = False
            self._config["auto_search_enabled"] = False

    def __repr__(self):
        return f"<ChatConfig(chat_id={self.chat_id})>"

    def __setattr__(self, name: str, value):
        if not name.startswith("_") and name in self._default_config:
            self._config[name] = value
            save_field(self.chat_id, name, value)
        else:
            super().__setattr__(name, value)

    def __getattribute__(self, name: str):
        if not name.startswith("_") and name in self._default_config:
            return self._config[name]
        else:
            return super().__getattribute__(name)
