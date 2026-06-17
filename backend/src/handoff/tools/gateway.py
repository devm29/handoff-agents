from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal, Protocol

import anyio
import structlog
from mcp import Client, MCPError, StdioServerParameters
from mcp_types import CONNECTION_CLOSED
from pydantic import BaseModel

from handoff.config import Settings
from handoff.errors import ToolError
from handoff.llm.types import ToolSpec

log = structlog.get_logger(__name__)

CONNECT_TIMEOUT_SECONDS = 10.0
CALL_TIMEOUT_SECONDS = 30.0
MAX_RECONNECT_BACKOFF_SECONDS = 15.0

_TRANSPORT_ERRORS = (anyio.ClosedResourceError, anyio.BrokenResourceError, anyio.EndOfStream, OSError)
_CALL_ERRORS = (*_TRANSPORT_ERRORS, TimeoutError)

ConnectionState = Literal["connecting", "connected", "closed"]


class ToolOutcome(BaseModel):
    content: str
    is_error: bool = False
    structured: Any = None


class ToolGateway(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome: ...


class MCPToolGateway:
    """Adapts an MCP client to the ToolGateway the agents depend on, and keeps it connected.

    The client lives in a holder task because its anyio cancel scopes must be exited by the
    task that entered them. When a call hits a transport failure (the stdio server died, the
    HTTP server went away) the holder tears the client down and connects a fresh one; the
    failed call surfaces as a retryable ToolError so the node retry policy tries again.
    """

    def __init__(self, factory: Callable[[], Client]) -> None:
        self._factory = factory
        self._client: Client | None = None
        self._ready = asyncio.Event()
        self._broken = asyncio.Event()
        self._stop_requested = asyncio.Event()
        self._holder: asyncio.Task[None] | None = None
        self._tools: list[ToolSpec] | None = None
        self._state: ConnectionState = "connecting"
        self.reconnects = 0

    def connection_state(self) -> ConnectionState:
        return self._state

    async def start(self) -> None:
        self._holder = asyncio.create_task(self._hold(), name="mcp-client")
        await self._current()

    async def stop(self) -> None:
        self._stop_requested.set()
        self._broken.set()
        if self._holder is not None:
            await asyncio.gather(self._holder, return_exceptions=True)
        self._state = "closed"

    async def list_tools(self) -> list[ToolSpec]:
        if self._tools is not None:
            return self._tools
        client = await self._current()
        try:
            listing = await client.list_tools()
        except MCPError as exc:
            self._on_failure(client, exc)
            raise ToolError(f"Could not list MCP tools: {exc}") from exc
        except _CALL_ERRORS as exc:
            self._on_failure(client, exc)
            raise ToolError(f"Could not list MCP tools: {exc!r}") from exc
        self._tools = [
            ToolSpec(name=t.name, description=t.description or t.name, input_schema=t.input_schema)
            for t in listing.tools
        ]
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        client = await self._current()
        try:
            result = await client.call_tool(name, arguments, read_timeout_seconds=CALL_TIMEOUT_SECONDS)
        except MCPError as exc:
            self._on_failure(client, exc)
            raise ToolError(f"MCP call to {name} failed: {exc}", details={"tool": name}) from exc
        except _CALL_ERRORS as exc:
            self._on_failure(client, exc)
            raise ToolError(f"MCP call to {name} failed: {exc!r}", details={"tool": name}) from exc

        if result.structured_content is not None:
            content = json.dumps(result.structured_content, ensure_ascii=False)
        else:
            content = "\n".join(block.text for block in result.content if block.type == "text")
        return ToolOutcome(content=content, is_error=result.is_error, structured=result.structured_content)

    async def _current(self) -> Client:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=CONNECT_TIMEOUT_SECONDS)
        except TimeoutError as exc:
            raise ToolError("The MCP tool server is not reachable") from exc
        if self._client is None:
            raise ToolError("The MCP tool server is not reachable")
        return self._client

    def _on_failure(self, client: Client, exc: BaseException) -> None:
        transport = isinstance(exc, _TRANSPORT_ERRORS) or (
            isinstance(exc, MCPError) and exc.code == CONNECTION_CLOSED
        )
        if transport and client is self._client and not self._broken.is_set():
            log.warning("mcp.connection_lost", error=repr(exc))
            self._ready.clear()
            self._broken.set()

    async def _hold(self) -> None:
        backoff = 0.5
        while not self._stop_requested.is_set():
            self._state = "connecting"
            try:
                async with self._factory() as client:
                    self._client = client
                    self._tools = None
                    self._state = "connected"
                    self._ready.set()
                    backoff = 0.5
                    await self._broken.wait()
            except Exception as exc:
                log.warning("mcp.connect_failed", error=repr(exc), retry_in=backoff)
            finally:
                self._client = None
                self._ready.clear()
            if self._stop_requested.is_set():
                return
            self._broken.clear()
            self.reconnects += 1
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_RECONNECT_BACKOFF_SECONDS)


def _client_factory(settings: Settings) -> Callable[[], Client]:
    match settings.mcp_transport:
        case "inprocess":
            from handoff.tools.server import build_server

            server = build_server()
            return lambda: Client(server)
        case "stdio":
            params = StdioServerParameters(command=sys.executable, args=["-m", "handoff.tools.server"])
            return lambda: Client(params)
        case "http":
            url = settings.mcp_url
            return lambda: Client(url)


@asynccontextmanager
async def connect_tools(settings: Settings) -> AsyncIterator[MCPToolGateway]:
    gateway = MCPToolGateway(_client_factory(settings))
    try:
        await gateway.start()
        yield gateway
    finally:
        await gateway.stop()
