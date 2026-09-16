"""End-to-end through the MCP protocol with an in-memory client. No network."""

from typing import Any

import pytest
import respx
from mcp import Client
from mcp.types import TextContent

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL as HIRO_BASE_URL
from stacks_mcp.clients.mempool import DEFAULT_BASE_URL
from stacks_mcp.server import mcp

from .conftest import GENESIS, SBTC_DEPLOYER


async def test_btc_tool_is_registered() -> None:
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


STX_BASE = f"{HIRO_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}"


def _mock_token_metadata(mocked_http: respx.MockRouter, fixtures: dict[str, Any]) -> None:
    for contract_id, body in fixtures.items():
        status = 404 if "error" in body else 200
        mocked_http.get(f"{HIRO_BASE_URL}/metadata/v1/ft/{contract_id}").respond(status, json=body)


async def test_all_four_tools_are_registered() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
    names = {tool.name for tool in result.tools}
    assert names == {
        "get_btc_balance",
        "get_stx_balance",
        "get_token_balances",
        "get_recent_transactions",
    }
    transactions = next(t for t in result.tools if t.name == "get_recent_transactions")
    assert transactions.input_schema["required"] == ["address", "chain"]


async def test_get_stx_balance_from_fixture(
    mocked_http: respx.MockRouter,
    stx_balance_fixture: dict[str, Any],
    nonces_fixture: dict[str, Any],
) -> None:
    mocked_http.get(f"{STX_BASE}/balances/stx").respond(200, json=stx_balance_fixture)
    mocked_http.get(f"{STX_BASE}/nonces").respond(200, json=nonces_fixture)
    async with Client(mcp) as client:
        result = await client.call_tool("get_stx_balance", {"address": SBTC_DEPLOYER})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["balance_ustx"] == 1_965_379_994
    assert data["balance_stx"] == "1965.379994"
    assert data["locked_ustx"] == 0
    assert data["locked_stx"] == "0.000000"
    assert data["nonce"] == 3833
    assert data["summary"] == ("SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833")


async def test_get_stx_balance_rejects_a_bitcoin_address(mocked_http: respx.MockRouter) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_stx_balance", {"address": GENESIS})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "Stacks principal" in result.content[0].text
    assert not mocked_http.calls


async def test_get_stx_balance_upstream_5xx_surfaces_as_error(
    mocked_http: respx.MockRouter, nonces_fixture: dict[str, Any]
) -> None:
    mocked_http.get(f"{STX_BASE}/balances/stx").respond(503, text="down")
    mocked_http.get(f"{STX_BASE}/nonces").respond(200, json=nonces_fixture)
    async with Client(mcp) as client:
        result = await client.call_tool("get_stx_balance", {"address": SBTC_DEPLOYER})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "Hiro API" in result.content[0].text
    assert "503" in result.content[0].text


async def test_get_token_balances_from_fixture(
    mocked_http: respx.MockRouter,
    ft_balances_fixture: dict[str, Any],
    ft_metadata_fixtures: dict[str, Any],
) -> None:
    mocked_http.get(f"{STX_BASE}/balances/ft").respond(200, json=ft_balances_fixture)
    _mock_token_metadata(mocked_http, ft_metadata_fixtures)
    async with Client(mcp) as client:
        result = await client.call_tool("get_token_balances", {"address": SBTC_DEPLOYER})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    tokens = data["tokens"]
    assert len(tokens) == 4
    by_contract = {token["contract_id"]: token for token in tokens}

    sbtc = by_contract[f"{SBTC_DEPLOYER}.sbtc-token"]
    assert sbtc["is_sbtc"]
    assert sbtc["symbol"] == "sBTC"
    assert sbtc["decimals"] == 8
    assert sbtc["balance_raw"] == "129"
    assert sbtc["balance"] == "0.00000129"

    teiko = by_contract["SP1T0VY3DNXRVP6HBM75DFWW0199CR0X15PC1D81B.teiko-token-stxcity"]
    assert not teiko["is_sbtc"]
    assert teiko["balance"] == "10.000000"

    # No metadata at all: falls back to the contract name and base units.
    unknown = by_contract["SP14XEKF7G8Q4WFYBSE77XSDMM67GTVF95R4V680.pixelstacks"]
    assert unknown["symbol"] == "pixelstacks"
    assert unknown["decimals"] == 0
    assert unknown["balance"] == "999000000"

    # Metadata without decimals: keeps its symbol, still base units.
    ralex = by_contract["SP37WN2BYHKZ90T1ATHTCNG8EFYHS3B49KNGS02ZK.RALEX"]
    assert ralex["symbol"] == "alexdao.org"
    assert ralex["balance"] == "154000"

    assert "metadata unknown for 2 of them" in data["summary"]


async def test_get_token_balances_upstream_5xx_surfaces_as_error(
    mocked_http: respx.MockRouter,
) -> None:
    mocked_http.get(f"{STX_BASE}/balances/ft").respond(500, text="boom")
    async with Client(mcp) as client:
        result = await client.call_tool("get_token_balances", {"address": SBTC_DEPLOYER})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "500" in result.content[0].text


async def test_get_recent_stx_transactions_from_fixture(
    mocked_http: respx.MockRouter, stx_transactions_fixture: dict[str, Any]
) -> None:
    route = mocked_http.get(f"{STX_BASE}/transactions").respond(200, json=stx_transactions_fixture)
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": SBTC_DEPLOYER, "chain": "stx", "limit": 10}
        )
    assert not result.is_error
    assert route.calls.last.request.url.params["limit"] == "10"
    data = result.structured_content
    assert data is not None
    assert data["chain"] == "stx"
    txs = data["transactions"]
    assert len(txs) == 10
    assert txs[0]["direction"] == "in"
    assert txs[0]["amount"] == "385.513100"
    assert txs[0]["kind"] == "token_transfer"
    assert txs[0]["timestamp"] == "2026-08-01T12:02:08Z"
    assert txs[1]["direction"] == "out"
    assert txs[1]["kind"] == "contract_call"
    assert txs[1]["counterparty"] == f"{SBTC_DEPLOYER}.sbtc-bootstrap-signers"
    assert all(tx["status"] == "confirmed" for tx in txs)


async def test_get_recent_btc_transactions_from_fixture(
    mocked_http: respx.MockRouter, genesis_txs_fixture: list[dict[str, Any]]
) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}/txs").respond(
        200, json=genesis_txs_fixture
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": GENESIS, "chain": "btc", "limit": 5}
        )
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    txs = data["transactions"]
    assert len(txs) == 5
    assert txs[0]["status"] == "pending"
    assert txs[0]["timestamp"] is None
    assert txs[0]["direction"] == "in"
    assert txs[0]["amount"] == "0.00003672"
    assert txs[2]["status"] == "confirmed"
    assert txs[2]["timestamp"] == "2026-09-16T15:11:18Z"


async def test_recent_transactions_defaults_to_ten(
    mocked_http: respx.MockRouter, genesis_txs_fixture: list[dict[str, Any]]
) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}/txs").respond(
        200, json=genesis_txs_fixture
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": GENESIS, "chain": "btc"}
        )
    data = result.structured_content
    assert data is not None
    assert len(data["transactions"]) == 10


@pytest.mark.parametrize("limit", [0, -1, 51, 1000])
async def test_recent_transactions_rejects_out_of_range_limits(
    mocked_http: respx.MockRouter, limit: int
) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": GENESIS, "chain": "btc", "limit": limit}
        )
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "between 1 and 50" in result.content[0].text
    assert not mocked_http.calls


async def test_recent_transactions_rejects_an_unknown_chain(
    mocked_http: respx.MockRouter,
) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": GENESIS, "chain": "doge"}
        )
    assert result.is_error
    assert not mocked_http.calls


async def test_recent_transactions_upstream_5xx_surfaces_as_error(
    mocked_http: respx.MockRouter,
) -> None:
    mocked_http.get(f"{STX_BASE}/transactions").respond(503, text="down")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_recent_transactions", {"address": SBTC_DEPLOYER, "chain": "stx"}
        )
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "Hiro API" in result.content[0].text
