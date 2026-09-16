"""`draft_stx_transfer`, through the MCP protocol. No network, no key, no signature."""

from typing import Any

import pytest
import respx
from mcp import Client
from mcp.types import TextContent

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL as HIRO_BASE_URL
from stacks_mcp.server import mcp

from .conftest import GENESIS, SBTC_DEPLOYER, load_fixture

STX_BASE = f"{HIRO_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}"
FEES_URL = f"{HIRO_BASE_URL}/extended/v2/mempool/fees"
RECIPIENT = "SP2ADT4TAV92SPBNP3WE9GPJ12F6CKGWMEJ1H1BB9"


def _mock_draft_reads(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(f"{STX_BASE}/balances/stx").respond(
        200, json=load_fixture("hiro", "v3_stx_balance_sbtc_deployer.json")
    )
    mocked_http.get(f"{STX_BASE}/nonces").respond(
        200, json=load_fixture("hiro", "v3_nonces_sbtc_deployer.json")
    )
    mocked_http.get(FEES_URL).respond(200, json=load_fixture("hiro", "v2_mempool_fees.json"))


async def _draft(arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(mcp) as client:
        result = await client.call_tool("draft_stx_transfer", arguments)
    assert not result.is_error
    data = result.structured_content
    assert data is not None
    return data


async def _error(arguments: dict[str, Any]) -> str:
    async with Client(mcp) as client:
        result = await client.call_tool("draft_stx_transfer", arguments)
    assert result.is_error
    assert isinstance(result.content[0], TextContent)
    return result.content[0].text


async def test_the_docstring_says_it_neither_signs_nor_broadcasts() -> None:
    """The docstring is what an agent reads before calling it, so the ceiling lives there."""
    async with Client(mcp) as client:
        result = await client.list_tools()
    draft = next(tool for tool in result.tools if tool.name == "draft_stx_transfer")
    assert draft.description is not None
    assert "neither signs nor broadcasts anything" in draft.description
    assert "The caller holds no key" in draft.description
    assert draft.input_schema["required"] == ["sender", "recipient", "amount_ustx"]


async def test_a_draft_carries_the_nonce_the_fees_and_no_signature(
    mocked_http: respx.MockRouter,
) -> None:
    _mock_draft_reads(mocked_http)
    data = await _draft({"sender": SBTC_DEPLOYER, "recipient": RECIPIENT, "amount_ustx": 1_500_000})
    assert data["signed"] is False
    assert data["sender"] == SBTC_DEPLOYER
    assert data["recipient"] == RECIPIENT
    assert data["amount_ustx"] == 1_500_000
    assert data["amount_stx"] == "1.500000"
    assert data["memo"] is None
    assert data["nonce"] == 3833
    assert data["network"] == "mainnet"
    assert data["sender_balance_ustx"] == 1_965_379_994
    assert [fee["priority"] for fee in data["fees"]] == [
        "no_priority",
        "low_priority",
        "medium_priority",
        "high_priority",
    ]
    assert [fee["fee_ustx"] for fee in data["fees"]] == [1289, 2398, 3508, 4395]
    assert data["fees"][0]["fee_stx"] == "0.001289"
    assert data["summary"] == (
        "Unsigned draft: SM3VDX...JFQ4 would send 1.500000 STX to SP2ADT...1BB9 at nonce 3833, "
        "fee 0.001289 STX and up; the balance of 1965.379994 STX covers it. "
        "Not signed and not broadcast"
    )
    # Nothing that could sign or send: no key material, no serialised transaction.
    assert "signature" not in data
    assert "private_key" not in data


async def test_a_draft_returns_no_signature_and_never_posts(
    mocked_http: respx.MockRouter,
) -> None:
    """Every request is a GET. A broadcast would be a POST to /v2/transactions."""
    _mock_draft_reads(mocked_http)
    await _draft({"sender": SBTC_DEPLOYER, "recipient": RECIPIENT, "amount_ustx": 1})
    assert {call.request.method for call in mocked_http.calls} == {"GET"}


async def test_a_memo_is_carried_through(mocked_http: respx.MockRouter) -> None:
    _mock_draft_reads(mocked_http)
    data = await _draft(
        {
            "sender": SBTC_DEPLOYER,
            "recipient": RECIPIENT,
            "amount_ustx": 1_000_000,
            "memo": "invoice 42",
        }
    )
    assert data["memo"] == "invoice 42"


async def test_an_amount_beyond_the_balance_is_drafted_and_flagged(
    mocked_http: respx.MockRouter,
) -> None:
    """Drafting is not authorising, so an unaffordable amount is a note, not an error."""
    _mock_draft_reads(mocked_http)
    data = await _draft(
        {"sender": SBTC_DEPLOYER, "recipient": RECIPIENT, "amount_ustx": 9_000_000_000}
    )
    assert data["amount_stx"] == "9000.000000"
    assert "does not cover it" in data["summary"]


async def test_a_contract_cannot_be_the_sender(mocked_http: respx.MockRouter) -> None:
    """A contract holds STX but has no key, so it can never sign a transfer."""
    message = await _error(
        {
            "sender": f"{SBTC_DEPLOYER}.sbtc-token",
            "recipient": RECIPIENT,
            "amount_ustx": 1_000_000,
        }
    )
    assert "contract principal, which cannot send a transfer" in message
    assert not mocked_http.calls


async def test_a_contract_may_be_the_recipient(mocked_http: respx.MockRouter) -> None:
    _mock_draft_reads(mocked_http)
    contract = f"{SBTC_DEPLOYER}.sbtc-token"
    data = await _draft({"sender": SBTC_DEPLOYER, "recipient": contract, "amount_ustx": 1_000_000})
    assert data["recipient"] == contract


@pytest.mark.parametrize("amount", [0, -1, -1_000_000])
async def test_an_amount_below_one_micro_stx_is_rejected(
    mocked_http: respx.MockRouter, amount: int
) -> None:
    message = await _error({"sender": SBTC_DEPLOYER, "recipient": RECIPIENT, "amount_ustx": amount})
    assert "at least 1 micro-STX" in message
    assert not mocked_http.calls


async def test_a_bitcoin_address_is_rejected_on_either_side(
    mocked_http: respx.MockRouter,
) -> None:
    sender_error = await _error(
        {"sender": GENESIS, "recipient": RECIPIENT, "amount_ustx": 1_000_000}
    )
    recipient_error = await _error(
        {"sender": SBTC_DEPLOYER, "recipient": GENESIS, "amount_ustx": 1_000_000}
    )
    assert "Stacks principal" in sender_error
    assert "Stacks principal" in recipient_error
    assert not mocked_http.calls


async def test_a_memo_over_thirty_four_bytes_is_rejected(
    mocked_http: respx.MockRouter,
) -> None:
    message = await _error(
        {
            "sender": SBTC_DEPLOYER,
            "recipient": RECIPIENT,
            "amount_ustx": 1_000_000,
            "memo": "x" * 35,
        }
    )
    assert "memo is 35 bytes" in message
    assert not mocked_http.calls


async def test_a_memo_is_measured_in_bytes_not_characters(
    mocked_http: respx.MockRouter,
) -> None:
    """Nine emoji are nine characters and 36 bytes, so they do not fit."""
    message = await _error(
        {
            "sender": SBTC_DEPLOYER,
            "recipient": RECIPIENT,
            "amount_ustx": 1_000_000,
            "memo": "\U0001f7e0" * 9,
        }
    )
    assert "memo is 36 bytes" in message
    assert not mocked_http.calls


async def test_an_upstream_failure_surfaces_as_an_error(
    mocked_http: respx.MockRouter,
) -> None:
    """A draft is all or nothing: a missing nonce would make the payload wrong."""
    _mock_draft_reads(mocked_http)
    mocked_http.get(FEES_URL).respond(503, text="down")
    message = await _error(
        {"sender": SBTC_DEPLOYER, "recipient": RECIPIENT, "amount_ustx": 1_000_000}
    )
    assert "Hiro API" in message
    assert "503" in message
