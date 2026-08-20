from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
from telegram.error import BadRequest

from reverse_image_search_bot.bot import error_handler


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Query is too old and response timeout expired or query id is invalid",
        "Query_id_invalid",
    ],
)
async def test_stale_callback_query_is_not_reported(message):
    context = cast(Any, SimpleNamespace(error=BadRequest(message)))
    with patch("reverse_image_search_bot.bot.logger") as logger:
        await error_handler(object(), context)
    logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_other_bad_request_is_reported():
    context = cast(Any, SimpleNamespace(error=BadRequest("Something else broke")))
    with patch("reverse_image_search_bot.bot.logger") as logger:
        await error_handler(object(), context)
    logger.error.assert_called_once()
