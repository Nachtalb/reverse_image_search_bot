from cleverdict import CleverDict

from reverse_image_search_bot.settings import PIXIV_CONFIG


class PixivConfig:
    _default_config: dict[str, None | str] = {
        "refresh_token": None,
        "access_token": None,
    }

    refresh_token: str | None
    access_token: str | None

    def __init__(self):
        PIXIV_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        self._config = CleverDict(self._default_config)
        if PIXIV_CONFIG.is_file():
            self._config.update(CleverDict.from_json(file_path=PIXIV_CONFIG))
        self._config.save_path = PIXIV_CONFIG
        self._config.autosave(fullcopy=True)

    def __repr__(self):
        return "<PixivConfig(...)>"

    def __setattr__(self, name: str, value):
        if not name.startswith("_") and name in self._default_config:
            self._config[name] = value
        else:
            super().__setattr__(name, value)

    def __getattribute__(self, name: str):
        if not name.startswith("_") and name in self._default_config:
            return self._config[name]
        else:
            return super().__getattribute__(name)
