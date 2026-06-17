from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from handoff.config import Settings
from handoff.tools.gateway import MCPToolGateway, connect_tools


@pytest.fixture(scope="session")
async def tools() -> AsyncIterator[MCPToolGateway]:
    async with connect_tools(Settings(mcp_transport="inprocess")) as gateway:
        yield gateway
