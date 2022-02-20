from pathlib import Path

from cleverdict import CleverDict, get_app_dir

app_path = Path(get_app_dir("reverse_image_search_bot"))
app_path.mkdir(parents=True, exist_ok=True)


class PixivConfig:
    _default_config: dict[str, None | str] = {
        "refresh_token": None,
        "access_token": None,
    }

    refresh_token: str | None
    access_token: str | None

    def __init__(self):
        config_file = app_path / "pixiv.json"
        self._config = CleverDict(self._default_config)
        if config_file.is_file():
            self._config.update(CleverDict.from_json(file_path=config_file))
        self._config.save_path = config_file
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
