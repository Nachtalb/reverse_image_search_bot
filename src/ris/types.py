from typing import Any, Callable, Coroutine

from aiohttp import ClientSession

ENGINE = Callable[[str, ClientSession], Coroutine[Any, Any, dict[str, Any]]]
