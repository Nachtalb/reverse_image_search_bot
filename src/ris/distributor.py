import asyncio
from typing import Any, Callable, Sequence

from aiohttp import ClientSession

from .cache import SOURCE_CACHE
from .providers import PROVIDERS
from .types import Normalized, Source


class Distributor:
    def __init__(
        self,
        callback: Callable[..., Any],
        callback_kwargs: dict[str, Any],
        session: ClientSession,
        *,
        use_source_cache: bool = True,
    ) -> None:
        self.session = session
        self.tasks: list[asyncio.Task[None]] = []
        self.callback = callback
        self.callback_kwargs = callback_kwargs
        self.use_source_cache = use_source_cache

    def distribute(
        self, data: Sequence[Normalized | None], pre_process: Callable[[Normalized], Normalized | None] | None = None
    ) -> None:
        for item in data:
            if not item:
                continue

            if pre_process:
                item = pre_process(item)

                if not item:
                    continue

            loop = asyncio.get_event_loop()
            task = asyncio.Task(self.run_task(item), loop=loop, eager_start=True)
            self.tasks.append(task)

    async def join(self, return_exceptions: bool = True) -> None:
        await asyncio.gather(*self.tasks, return_exceptions=return_exceptions)

    async def cancel(self, wait: bool = False) -> None:
        for task in self.tasks:
            task.cancel()

        if wait:
            await self.join()

    async def run_task(self, data: Normalized) -> None:
        platform = data["platform"]
        engine = data["engine"]
        file_id = data["file_id"]

        platform_cache = SOURCE_DIR / platform
        cache_file = await cache_path(platform_cache, data["file_id"] + ".json")

        if self.use_source_cache:
            if await SOURCE_CACHE.exists(file_id, sub_dir=platform):
                source_dict = await SOURCE_CACHE.get_json(file_id, sub_dir=platform)
                if not source_dict:
                    return
                source = Source.from_dict(source_dict)
                asyncio.create_task(self.callback(**self.callback_kwargs, source=source))
                return

        if func := PROVIDERS.get(platform):
            try:
                result = await func(data, self.session, self)
                if not result and (func := PROVIDERS.get(engine)):  # type: ignore[call-overload]
                    result = await func(data, self.session, self)

                await SOURCE_CACHE.set_json(file_id, result.dict() if result else None, sub_dir=platform)
            except asyncio.CancelledError:
                return

            if not result:
                return
            asyncio.create_task(self.callback(**self.callback_kwargs, source=result))
