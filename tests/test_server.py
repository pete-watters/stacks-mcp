"""End-to-end through the MCP protocol with an in-memory client. No network."""

from typing import Any

import pytest
import respx
from mcp import Client
from mcp.types import TextContent

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL as HIRO_BASE_URL
from stacks_mcp.clients.mempool import DEFAULT_BASE_URL
from stacks_mcp.server import mcp

from .conftest import GENESIS, SBTC_DEPLOYER, load_fixture


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


async def test_all_five_tools_are_registered() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
    names = {tool.name for tool in result.tools}
    assert names == {
        "get_btc_balance",
        "get_stx_balance",
        "get_token_balances",
        "get_recent_transactions",
        "explain_transaction",
    }
    transactions = next(t for t in result.tools if t.name == "get_recent_transactions")
    assert transactions.input_schema["required"] == ["address", "chain"]
    explain = next(t for t in result.tools if t.name == "explain_transaction")
    assert explain.input_schema["required"] == ["txid", "chain"]
    assert explain.description is not None
    # The docstring is what an agent reads to decide whether to call this, so it
    # has to say the decode is deterministic rather than a model.
    assert "deterministic" in explain.description


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


POX4_TXID = "0x995fb653065c74596b63e6cc9c10fb8fa7b8f3574d5ea089b45d3e11d9e7336e"
SBTC_DEPOSIT_TXID = "0xd044e48842e5ba34e1d05bebd8e0a9519192624d61114848460dcba4c9611db6"
DEPLOY_TXID = "0xbf406ea1fbd35aa21917cbb144080bdb7e06b2e45ddd162b2ad9e4b4e522577d"
BTC_TXID = "ec786e157e41a498dde976c5e4e324cb7bb6557832ebc0f3d67f0ffd7d5812fb"


def _mock_stx_transaction(
    mocked_http: respx.MockRouter, txid: str, tx_fixture: str, events_fixture: str | None = None
) -> None:
    url = f"{HIRO_BASE_URL}/extended/v3/transactions/{txid}"
    mocked_http.get(url).respond(200, json=load_fixture("hiro", tx_fixture))
    if events_fixture is not None:
        mocked_http.get(f"{url}/events").respond(200, json=load_fixture("hiro", events_fixture))


async def test_explain_stacking_transaction_end_to_end(mocked_http: respx.MockRouter) -> None:
    """0x995fb653065c74596b63e6cc9c10fb8fa7b8f3574d5ea089b45d3e11d9e7336e."""
    _mock_stx_transaction(
        mocked_http, POX4_TXID, "v3_tx_pox4_stack_stx.json", "v3_tx_events_pox4_stack_stx.json"
    )
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": POX4_TXID, "chain": "stx"})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["kind"] == "stacking"
    assert data["summary"] == (
        "Stacking: SP14S2...KHCB locked 4491100.000000 STX for 1 cycle via pox-4::stack-stx."
    )
    assert data["fee"] == "0.003102 STX (3,102 uSTX)"
    assert data["block_height"] == 8647822


async def test_explain_asks_for_function_args(mocked_http: respx.MockRouter) -> None:
    """A contract call without `function_args` cannot say how much was locked."""
    _mock_stx_transaction(
        mocked_http, POX4_TXID, "v3_tx_pox4_stack_stx.json", "v3_tx_events_pox4_stack_stx.json"
    )
    async with Client(mcp) as client:
        await client.call_tool("explain_transaction", {"txid": POX4_TXID, "chain": "stx"})
    detail = next(c for c in mocked_http.calls if "/events" not in str(c.request.url))
    assert detail.request.url.params["include"] == "function_args"


async def test_explain_sbtc_deposit_end_to_end(mocked_http: respx.MockRouter) -> None:
    """0xd044e48842e5ba34e1d05bebd8e0a9519192624d61114848460dcba4c9611db6."""
    _mock_stx_transaction(
        mocked_http, SBTC_DEPOSIT_TXID, "v3_tx_sbtc_deposit.json", "v3_tx_events_sbtc_deposit.json"
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "explain_transaction", {"txid": SBTC_DEPOSIT_TXID, "chain": "stx"}
        )
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["kind"] == "sbtc_deposit"
    assert data["summary"] == (
        "sBTC deposit of 0.00098076 sBTC minted to SP2WS9...JF7A "
        "via sbtc-deposit::complete-deposit-wrapper."
    )


async def test_explain_accepts_a_stacks_txid_without_the_prefix(
    mocked_http: respx.MockRouter,
) -> None:
    """Hiro wants `0x`; a user pasting a bare id should not have to know that."""
    _mock_stx_transaction(
        mocked_http, POX4_TXID, "v3_tx_pox4_stack_stx.json", "v3_tx_events_pox4_stack_stx.json"
    )
    async with Client(mcp) as client:
        result = await client.call_tool(
            "explain_transaction", {"txid": POX4_TXID[2:].upper(), "chain": "stx"}
        )
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["txid"] == POX4_TXID


async def test_explain_skips_the_events_call_when_there_are_none(
    mocked_http: respx.MockRouter,
) -> None:
    """Events are a second request, so a deploy with none must not make it."""
    _mock_stx_transaction(mocked_http, DEPLOY_TXID, "v3_tx_contract_deploy.json")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "explain_transaction", {"txid": DEPLOY_TXID, "chain": "stx"}
        )
    assert not result.is_error
    assert not any("/events" in str(call.request.url) for call in mocked_http.calls)


async def test_explain_btc_transaction_end_to_end(mocked_http: respx.MockRouter) -> None:
    """ec786e157e41a498dde976c5e4e324cb7bb6557832ebc0f3d67f0ffd7d5812fb."""
    mocked_http.get(f"{DEFAULT_BASE_URL}/tx/{BTC_TXID}").respond(
        200, json=load_fixture("mempool", "tx_simple_transfer.json")
    )
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": BTC_TXID, "chain": "btc"})
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    assert data["kind"] == "btc_transfer"
    assert data["summary"] == (
        "BTC transfer of 0.01310200 BTC to 2 addresses, 1 input, 2 outputs, "
        "fee 45,900 sats (300.00 sat/vB)."
    )


@pytest.mark.parametrize(
    "bad",
    ["", "not-a-txid", "0x123", POX4_TXID + "ff", "0x" + "z" * 64],
)
async def test_explain_rejects_a_malformed_txid(mocked_http: respx.MockRouter, bad: str) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": bad, "chain": "stx"})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "64 hex characters" in result.content[0].text or "empty" in result.content[0].text
    assert not mocked_http.calls


async def test_explain_reports_an_unknown_stacks_txid_plainly(
    mocked_http: respx.MockRouter,
) -> None:
    """A 404 means no such transaction, which is not the same as the API failing."""
    mocked_http.get(f"{HIRO_BASE_URL}/extended/v3/transactions/{POX4_TXID}").respond(
        404, json={"error": "not found"}
    )
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": POX4_TXID, "chain": "stx"})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    # The SDK prefixes the message with the tool name; the sentence is ours.
    assert result.content[0].text.endswith(f"no Stacks transaction found with id {POX4_TXID}")
    assert "Traceback" not in result.content[0].text
    assert "404" not in result.content[0].text


async def test_explain_reports_an_unknown_bitcoin_txid_plainly(
    mocked_http: respx.MockRouter,
) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/tx/{BTC_TXID}").respond(404, text="Transaction not found")
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": BTC_TXID, "chain": "btc"})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text.endswith(f"no Bitcoin transaction found with id {BTC_TXID}")


async def test_explain_surfaces_an_upstream_outage_as_an_outage(
    mocked_http: respx.MockRouter,
) -> None:
    """A 503 keeps the service and status code, so the caller can tell them apart."""
    mocked_http.get(f"{HIRO_BASE_URL}/extended/v3/transactions/{POX4_TXID}").respond(
        503, text="down"
    )
    async with Client(mcp) as client:
        result = await client.call_tool("explain_transaction", {"txid": POX4_TXID, "chain": "stx"})
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    assert "Hiro API" in result.content[0].text
    assert "503" in result.content[0].text
