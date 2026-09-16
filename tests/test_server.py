"""End-to-end through the MCP protocol with an in-memory client. No network."""

from typing import Any

import pytest
import respx
from mcp import Client
from mcp.types import TextContent

from stacks_mcp.clients.mempool import DEFAULT_BASE_URL
from stacks_mcp.server import mcp

GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


async def test_tool_is_registered() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
    names = {tool.name for tool in result.tools}
    assert "get_btc_balance" in names
    tool = next(t for t in result.tools if t.name == "get_btc_balance")
    assert tool.description is not None
    assert "read-only" in tool.description
    assert tool.input_schema["required"] == ["address"]


async def test_get_btc_balance_from_fixture(
    mocked_http: respx.MockRouter, genesis_fixture: dict[str, Any]
) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(200, json=genesis_fixture)
    async with Client(mcp) as client:
        result = await client.call_tool("get_btc_balance", {"address": GENESIS})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["address"] == GENESIS
    assert data["confirmed_sats"] == 5747023635
    assert data["unconfirmed_sats"] == 4218
    assert data["confirmed_btc"] == "57.47023635"
    assert data["tx_count"] == 65805
    assert data["summary"] == (
        "1A1zP1...vfNa holds 57.47023635 BTC across 65,805 transactions, 4,218 sats unconfirmed"
    )


@pytest.mark.parametrize("bad", ["", "hello", "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7"])
async def test_invalid_address_returns_clear_error(mocked_http: respx.MockRouter, bad: str) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_btc_balance", {"address": bad})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "Bitcoin address" in result.content[0].text or "empty" in result.content[0].text
    assert not mocked_http.calls


async def test_upstream_5xx_surfaces_as_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(503, text="down")
    async with Client(mcp) as client:
        result = await client.call_tool("get_btc_balance", {"address": GENESIS})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "mempool.space" in result.content[0].text
    assert "503" in result.content[0].text
