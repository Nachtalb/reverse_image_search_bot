"""Regression: the report-server runner must never land in bot_data.

An aiohttp AppRunner is unpicklable; one unpicklable value in bot_data makes
every PicklePersistence flush fail silently (bot_data.pickle froze for 6 days
in prod, dropping feedback reply mappings across restarts).
"""

import pickle
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from reverse_image_search_bot import bot as bot_module


@pytest.mark.asyncio
async def test_report_runner_not_in_bot_data():
    app = MagicMock()
    app.bot_data = {}
    unpicklable_runner = MagicMock()

    with (
        patch.object(bot_module.settings, "REPORT_SERVER_ENABLED", True),
        patch(
            "reverse_image_search_bot.abuse_report.server.start_report_server",
            AsyncMock(return_value=unpicklable_runner),
        ),
    ):
        await bot_module._start_report_server(app)

    assert bot_module._report_runner is unpicklable_runner
    pickle.dumps(app.bot_data)  # must stay picklable
