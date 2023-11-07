import logging
from typing import Any

from ris import provider_engines
from ris.provider_engines import ProviderData

logger = logging.getLogger("ris.provider")


async def fetch_provider_data(
    search_engine: str, provider_name: str, provider_id: str | int, extra_data: Any
) -> ProviderData | None:
    log_prefix = f"[{provider_id}].fetch_provider_data:"
    logger.info(f"{log_prefix} finding provider for {provider_name=}")

    if provider := getattr(provider_engines, provider_name, None):
        logger.debug(f"{log_prefix} found provider '{provider_name}'")
        result = await provider(provider_id, extra_data)
        if result:
            logger.debug(f"{log_prefix} provider '{provider_name}' provided data")
            return result  # type: ignore[no-any-return]
        logger.debug(f"{log_prefix} provider '{provider_name}' returned trying generic provider")

    if provider := getattr(provider_engines, f"{search_engine}_generic", None):
        logger.debug(f"{log_prefix} found generic search provider '{search_engine}_generic'")
        if result := await provider(provider_name, provider_id, extra_data):
            logger.debug(f"{log_prefix} generic search provider '{search_engine}_generic' provided data")
            return result  # type: ignore[no-any-return]
    elif provider := getattr(provider_engines, "generic", None):
        logger.debug(f"{log_prefix} using generic provider 'generic'")
        if result := await provider(provider_name, provider_id, extra_data):
            logger.debug(f"{log_prefix} generic provider 'generic' provided data")
            return result  # type: ignore[no-any-return]

    logger.warning(f"{log_prefix} no provider found for '{provider_name}'")
    return None
