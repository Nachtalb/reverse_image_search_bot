from pathlib import Path
from time import time
from typing import Type

from cleverdict import CleverDict, get_app_dir
from telegram import User

app_path = Path(get_app_dir("reverse_image_search_bot"))
app_path.mkdir(parents=True, exist_ok=True)


def single(cls: Type["UserConfig"]):
    def get_instance(user: User | int):
        id: int = user.id if isinstance(user, User) else user
        if not hasattr(cls, "__loaded_users"):
            cls.__loaded_users = {}

        if id in cls.__loaded_users:
            return cls.__loaded_users[id]
        else:
            new_user = cls(id)
            cls.__loaded_users[id] = new_user
            return new_user

    return get_instance


@single
class UserConfig:
    _default_config: dict[str | int, str | int | bool] = {
        "auto_search_enabled": True,
        "failures_in_a_row": 0,
    }
    __loaded_users: dict[int, "UserConfig"] = {}  # type: ignore

    auto_search_enabled: bool
    failures_in_a_row: int

    def __init__(self, user: User | int):
        self.id: int = user.id if isinstance(user, User) else user
        self.last_auto_search: float | None = None

        config_file = app_path / (str(self.id) + ".json")
        self._config = CleverDict(self._default_config)
        if config_file.is_file():
            self._config.update(CleverDict.from_json(file_path=config_file))
        self._config.save_path = config_file
        self._config.autosave(fullcopy=True)

    def __repr__(self):
        return f"<UserConfig(user={self.id})>"

    def used_auto_search(self):
        self.last_auto_search = time()

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
