import asyncio
import logging
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
        self.log = logging.getLogger(self.__class__.__name__)
        self.log.info("Initializing distributor")
        self.log.debug(f"Callback: {callback}")
        self.log.debug(f"Callback kwargs: {callback_kwargs}")
        self.log.debug(f"Use source cache: {use_source_cache}")

        self.session = session
        self.tasks: list[asyncio.Task[None]] = []
        self.callback = callback
        self.callback_kwargs = callback_kwargs
        self.use_source_cache = use_source_cache

    def distribute(
        self, data: Sequence[Normalized | None], pre_process: Callable[[Normalized], Normalized | None] | None = None
    ) -> None:
        self.log.info(f"Distributing {len(data)} items")
        for index, item in enumerate(data, 1):
            if not item:
                self.log.debug("Skipping empty item {index}")
                continue

            if pre_process:
                item = pre_process(item)

                if not item:
                    self.log.debug(f"Skipping item {index} after pre-processing")
                    continue

            loop = asyncio.get_event_loop()
            task = asyncio.Task(self.run_task(item), loop=loop, eager_start=True)
            self.log.debug(f"Created task for {item['file_id']} {item['platform']}")
            self.tasks.append(task)

    async def join(self, return_exceptions: bool = True) -> None:
        self.log.info("Waiting for tasks to finish")
        await asyncio.gather(*self.tasks, return_exceptions=return_exceptions)

    async def cancel(self, wait: bool = False) -> None:
        self.log.info("Cancelling tasks")
        for task in self.tasks:
            task.cancel()
            self.log.debug(f"Cancelled task {task}")

        if wait:
            self.log.info("Waiting for tasks to finish")
            await self.join()
        else:
            self.log.info("Tasks will not be waited for")

    async def run_task(self, data: Normalized) -> None:
        platform = data["platform"]
        engine = data["engine"]
        file_id = data["file_id"]

        self.log.info(f"Running task for {file_id} on {platform}")

        loop = asyncio.get_event_loop()
        if self.use_source_cache:
            self.log.debug(f"Checking source cache for {file_id} on {platform}")
            if await SOURCE_CACHE.exists(file_id, sub_dir=platform):
                self.log.debug(
                    f"Source cache hit for {file_id} on {platform} at {await SOURCE_CACHE.cache_path(file_id, sub_dir=platform)}"
                )
                source_dict = await SOURCE_CACHE.get_json(file_id, sub_dir=platform)
                if not source_dict:
                    self.log.debug("Skipping empty source")
                    return
                self.log.debug(f"Creating source object for {file_id} on {platform}")
                source = Source.from_dict(source_dict)
                self.log.debug(f"Running callback for {file_id} on {platform}")
                asyncio.Task(self.callback(**self.callback_kwargs, source=source), loop=loop, eager_start=True)
                return

        if func := PROVIDERS.get(platform):
            try:
                self.log.debug(f"Retrieving source for {file_id} on {platform}")
                result = await func(data, self.session, self)
                if not result and (func := PROVIDERS.get(engine)):  # type: ignore[call-overload]
                    self.log.debug(f"Provider {platform} failed, raw engine data from engine: {engine}")
                    self.log.debug(f"Retrieving source for {file_id} on {engine}")
                    result = await func(data, self.session, self)

                self.log.debug(f"Saving source for {file_id} on {platform}")
                await SOURCE_CACHE.set_json(file_id, result.dict() if result else None, sub_dir=platform)
            except asyncio.CancelledError:
                self.log.debug(f"Task for {file_id} on {platform} was cancelled")
                return

            if not result:
                self.log.debug("Skipping empty source")
                return

            self.log.debug(f"Running callback for {file_id} on {platform}")
            asyncio.Task(self.callback(**self.callback_kwargs, source=result), loop=loop, eager_start=True)
