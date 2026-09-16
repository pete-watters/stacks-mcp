"""The address-summary resource, through the MCP protocol. No network."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import TextResourceContents

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL as HIRO_BASE_URL
from stacks_mcp.server import mcp

from .conftest import GENESIS, SBTC_DEPLOYER, load_fixture

STX_BASE = f"{HIRO_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}"
SUMMARY_URI = f"stacks://address/{SBTC_DEPLOYER}/summary"


def _mock_token_metadata(mocked_http: respx.MockRouter, fixtures: dict[str, Any]) -> None:
    for contract_id, body in fixtures.items():
        status = 404 if "error" in body else 200
        mocked_http.get(f"{HIRO_BASE_URL}/metadata/v1/ft/{contract_id}").respond(status, json=body)


def _mock_all_three(mocked_http: respx.MockRouter, fixtures: dict[str, Any]) -> None:
    """Every upstream the snapshot reads, answering from recorded mainnet bodies."""
    mocked_http.get(f"{STX_BASE}/balances/stx").respond(
        200, json=load_fixture("hiro", "v3_stx_balance_sbtc_deployer.json")
    )
    mocked_http.get(f"{STX_BASE}/nonces").respond(
        200, json=load_fixture("hiro", "v3_nonces_sbtc_deployer.json")
    )
    mocked_http.get(f"{STX_BASE}/balances/ft").respond(
        200, json=load_fixture("hiro", "v3_ft_balances_sbtc_deployer.json")
    )
    mocked_http.get(f"{STX_BASE}/transactions").respond(
        200, json=load_fixture("hiro", "v3_transactions_sbtc_deployer.json")
    )
    _mock_token_metadata(mocked_http, fixtures)


async def _read(uri: str) -> dict[str, Any]:
    async with Client(mcp) as client:
        result = await client.read_resource(uri)
    assert len(result.contents) == 1
    content = result.contents[0]
    assert isinstance(content, TextResourceContents)
    assert content.mime_type == "application/json"
    parsed: dict[str, Any] = json.loads(content.text)
    return parsed


async def test_the_summary_is_a_resource_template_not_a_tool() -> None:
    """A snapshot of an address is data at a URI, so it is a template, not a sixth tool."""
    async with Client(mcp) as client:
        templates = await client.list_resource_templates()
        tools = await client.list_tools()
    uris = {template.uri_template for template in templates.resource_templates}
    assert "stacks://address/{address}/summary" in uris
    assert "address_summary" not in {tool.name for tool in tools.tools}
    template = next(t for t in templates.resource_templates if t.uri_template.endswith("/summary"))
    assert template.name == "stacks_address_summary"
    assert template.mime_type == "application/json"
    assert template.description is not None
    assert "read-only" in template.description


async def test_summary_combines_all_three_reads(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    _mock_all_three(mocked_http, ft_metadata_fixtures)
    data = await _read(SUMMARY_URI)
    assert data["address"] == SBTC_DEPLOYER
    assert data["failures"] == []
    assert data["stx"]["balance_stx"] == "1965.379994"
    assert data["stx"]["nonce"] == 3833
    assert len(data["tokens"]["tokens"]) == 4
    assert any(token["is_sbtc"] for token in data["tokens"]["tokens"])
    assert len(data["transactions"]["transactions"]) == 10
    assert data["summary"] == (
        "SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833; "
        "holds 4 fungible tokens: 999000000 pixelstacks, 154000 alexdao.org, "
        "0.00000129 sBTC and 1 more; metadata unknown for 2 of them, shown in base units; "
        "has 10 recent STX transactions (1 in, 9 out), most recent 2026-08-01T12:02:08Z"
    )


async def test_summary_asks_for_ten_transactions(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    _mock_all_three(mocked_http, ft_metadata_fixtures)
    route = mocked_http.get(f"{STX_BASE}/transactions")
    await _read(SUMMARY_URI)
    assert route.calls.last.request.url.params["limit"] == "10"


async def test_one_failed_read_does_not_lose_the_rest(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    """Token metadata is down; the balance and the history still arrive."""
    _mock_all_three(mocked_http, ft_metadata_fixtures)
    mocked_http.get(f"{STX_BASE}/balances/ft").respond(503, text="down")
    data = await _read(SUMMARY_URI)
    assert data["tokens"] is None
    assert data["stx"]["balance_stx"] == "1965.379994"
    assert len(data["transactions"]["transactions"]) == 10
    assert data["failures"] == [
        {"part": "token balances", "reason": "Hiro API request failed (503): down"}
    ]
    assert data["summary"].endswith("; could not read token balances")
    assert "1965.379994 STX" in data["summary"]


async def test_a_failed_read_names_itself_in_the_summary(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    """The nonce endpoint fails, so the whole STX part goes; the other two stay."""
    _mock_all_three(mocked_http, ft_metadata_fixtures)
    mocked_http.get(f"{STX_BASE}/nonces").respond(500, text="boom")
    data = await _read(SUMMARY_URI)
    assert data["stx"] is None
    assert data["tokens"] is not None
    assert [failure["part"] for failure in data["failures"]] == ["STX balance"]
    assert data["summary"].startswith("SM3VDX...JFQ4 holds 4 fungible tokens")
    assert data["summary"].endswith("; could not read STX balance")


async def test_every_read_failing_still_returns_a_snapshot(
    mocked_http: respx.MockRouter,
) -> None:
    """All three down is still a result, not an error: the caller learns what is wrong."""
    for path in ("balances/stx", "nonces", "balances/ft", "transactions"):
        mocked_http.get(f"{STX_BASE}/{path}").respond(503, text="down")
    data = await _read(SUMMARY_URI)
    assert data["stx"] is None
    assert data["tokens"] is None
    assert data["transactions"] is None
    assert [failure["part"] for failure in data["failures"]] == [
        "STX balance",
        "token balances",
        "recent transactions",
    ]
    assert data["summary"] == (
        "SM3VDX...JFQ4: nothing could be read, "
        "STX balance, token balances, recent transactions all failed"
    )


async def test_the_three_reads_go_out_together(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    """Every read starts before any of them finishes, which is what concurrent means.

    Run serially, the first response would arrive before the second request
    left. Each mock records when it is entered and when it answers, so the
    order of that log is the proof.
    """
    events: list[str] = []

    def _slow(name: str, body: Any) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
        async def respond(_: httpx.Request) -> httpx.Response:
            events.append(f"start {name}")
            await asyncio.sleep(0.01)
            events.append(f"end {name}")
            return httpx.Response(200, json=body)

        return respond

    mocked_http.get(f"{STX_BASE}/balances/stx").mock(
        side_effect=_slow("stx", load_fixture("hiro", "v3_stx_balance_sbtc_deployer.json"))
    )
    mocked_http.get(f"{STX_BASE}/nonces").respond(
        200, json=load_fixture("hiro", "v3_nonces_sbtc_deployer.json")
    )
    mocked_http.get(f"{STX_BASE}/balances/ft").mock(
        side_effect=_slow("tokens", load_fixture("hiro", "v3_ft_balances_sbtc_deployer.json"))
    )
    mocked_http.get(f"{STX_BASE}/transactions").mock(
        side_effect=_slow("txs", load_fixture("hiro", "v3_transactions_sbtc_deployer.json"))
    )
    _mock_token_metadata(mocked_http, ft_metadata_fixtures)

    data = await _read(SUMMARY_URI)
    assert data["failures"] == []
    assert set(events[:3]) == {"start stx", "start tokens", "start txs"}


async def test_a_malformed_address_is_rejected_before_any_request(
    mocked_http: respx.MockRouter,
) -> None:
    uri = f"stacks://address/{GENESIS}/summary"
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as caught:
            await client.read_resource(uri)
    assert "Stacks principal" in str(caught.value)
    assert not mocked_http.calls
