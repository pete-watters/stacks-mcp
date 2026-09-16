from typing import Any

import httpx
import pytest
import respx

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL, HiroClient, api_key, base_url
from stacks_mcp.errors import UpstreamError

from .conftest import SBTC_DEPLOYER, load_fixture

STX_BALANCE_URL = f"{DEFAULT_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}/balances/stx"
NONCES_URL = f"{DEFAULT_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}/nonces"
FT_BALANCES_URL = f"{DEFAULT_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}/balances/ft"
TRANSACTIONS_URL = f"{DEFAULT_BASE_URL}/extended/v3/principals/{SBTC_DEPLOYER}/transactions"
SBTC_METADATA_URL = f"{DEFAULT_BASE_URL}/metadata/v1/ft/{SBTC_DEPLOYER}.sbtc-token"
MEMPOOL_FEES_URL = f"{DEFAULT_BASE_URL}/extended/v2/mempool/fees"


async def test_get_stx_balance_parses_fixture(
    mocked_http: respx.MockRouter, stx_balance_fixture: dict[str, Any]
) -> None:
    mocked_http.get(STX_BALANCE_URL).respond(200, json=stx_balance_fixture)
    client = HiroClient()
    try:
        balance = await client.get_stx_balance(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert balance.balance_ustx == 1_965_379_994
    assert balance.locked is None
    assert balance.locked_ustx == 0


async def test_locked_balance_is_read_from_the_lock_block(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(STX_BALANCE_URL).respond(
        200,
        json={
            "balance": "3000000000",
            "available": "1000000000",
            "locked": {
                "amount": "2000000000",
                "pox_version": 4,
                "lock_tx_id": "0x" + "ab" * 32,
                "stacks_lock_height": 1,
                "burn_lock_height": 2,
                "burn_unlock_height": 3,
            },
            "mempool": None,
        },
    )
    client = HiroClient()
    try:
        balance = await client.get_stx_balance(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert balance.balance_ustx == 3_000_000_000
    assert balance.locked_ustx == 2_000_000_000


async def test_get_nonces_parses_fixture(
    mocked_http: respx.MockRouter, nonces_fixture: dict[str, Any]
) -> None:
    mocked_http.get(NONCES_URL).respond(200, json=nonces_fixture)
    client = HiroClient()
    try:
        nonces = await client.get_nonces(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert nonces.next_nonce == 3833
    assert nonces.last_confirmed_nonce == 3832


async def test_get_ft_balances_parses_fixture(
    mocked_http: respx.MockRouter, ft_balances_fixture: dict[str, Any]
) -> None:
    mocked_http.get(FT_BALANCES_URL).respond(200, json=ft_balances_fixture)
    client = HiroClient()
    try:
        balances = await client.get_ft_balances(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert balances.total == 4
    assert balances.results[2].contract_id == f"{SBTC_DEPLOYER}.sbtc-token"
    assert balances.results[2].balance == "129"


async def test_get_transactions_parses_fixture(
    mocked_http: respx.MockRouter, stx_transactions_fixture: dict[str, Any]
) -> None:
    route = mocked_http.get(TRANSACTIONS_URL).respond(200, json=stx_transactions_fixture)
    client = HiroClient()
    try:
        page = await client.get_transactions(SBTC_DEPLOYER, 10)
    finally:
        await client.aclose()
    assert route.calls.last.request.url.params["limit"] == "10"
    assert page.total == 3861
    assert len(page.results) == 10
    first = page.results[0]
    assert first.transaction.type == "token_transfer"
    assert first.involvement == "affected"
    assert first.balance_changes.stx.received == "385513100"


async def test_get_ft_metadata_parses_fixture(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(SBTC_METADATA_URL).respond(
        200,
        json={"tx_id": "0x00", "sender_address": SBTC_DEPLOYER, "symbol": "sBTC", "decimals": 8},
    )
    client = HiroClient()
    try:
        metadata = await client.get_ft_metadata(f"{SBTC_DEPLOYER}.sbtc-token")
    finally:
        await client.aclose()
    assert metadata is not None
    assert metadata.symbol == "sBTC"
    assert metadata.decimals == 8


@pytest.mark.parametrize("status", [404, 422])
async def test_missing_metadata_is_not_an_error(mocked_http: respx.MockRouter, status: int) -> None:
    mocked_http.get(SBTC_METADATA_URL).respond(status, json={"error": "Token not found"})
    client = HiroClient()
    try:
        assert await client.get_ft_metadata(f"{SBTC_DEPLOYER}.sbtc-token") is None
    finally:
        await client.aclose()


async def test_metadata_5xx_raises_upstream_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(SBTC_METADATA_URL).respond(503, text="down")
    client = HiroClient()
    try:
        with pytest.raises(UpstreamError):
            await client.get_ft_metadata(f"{SBTC_DEPLOYER}.sbtc-token")
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [500, 502, 503, 429])
async def test_non_2xx_raises_upstream_error(mocked_http: respx.MockRouter, status: int) -> None:
    mocked_http.get(STX_BALANCE_URL).respond(status, text="nope")
    client = HiroClient()
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await client.get_stx_balance(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert excinfo.value.status_code == status
    assert excinfo.value.service == "Hiro API"


async def test_transport_error_raises_upstream_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(STX_BALANCE_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    client = HiroClient()
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await client.get_stx_balance(SBTC_DEPLOYER)
    finally:
        await client.aclose()
    assert excinfo.value.status_code is None


async def test_unexpected_body_raises_upstream_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(STX_BALANCE_URL).respond(200, json={"foo": 1})
    client = HiroClient()
    try:
        with pytest.raises(UpstreamError):
            await client.get_stx_balance(SBTC_DEPLOYER)
    finally:
        await client.aclose()


async def test_api_key_is_sent_only_when_set(
    mocked_http: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    stx_balance_fixture: dict[str, Any],
) -> None:
    route = mocked_http.get(STX_BALANCE_URL).respond(200, json=stx_balance_fixture)
    monkeypatch.delenv("HIRO_API_KEY", raising=False)
    client = HiroClient()
    try:
        await client.get_stx_balance(SBTC_DEPLOYER)
        assert "x-api-key" not in route.calls.last.request.headers
        monkeypatch.setenv("HIRO_API_KEY", "secret-key")
        await client.get_stx_balance(SBTC_DEPLOYER)
        assert route.calls.last.request.headers["x-api-key"] == "secret-key"
    finally:
        await client.aclose()


async def test_get_mempool_fees_reads_the_token_transfer_tiers(
    mocked_http: respx.MockRouter,
) -> None:
    """The tiers are absolute micro-STX fees, not a rate per byte."""
    mocked_http.get(MEMPOOL_FEES_URL).respond(
        200, json=load_fixture("hiro", "v2_mempool_fees.json")
    )
    client = HiroClient()
    try:
        fees = await client.get_mempool_fees()
    finally:
        await client.aclose()
    assert fees.token_transfer.no_priority == 1289
    assert fees.token_transfer.low_priority == 2398
    assert fees.token_transfer.medium_priority == 3508
    assert fees.token_transfer.high_priority == 4395


def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIRO_BASE_URL", "http://localhost:3999/")
    assert base_url() == "http://localhost:3999"
    monkeypatch.delenv("HIRO_BASE_URL")
    assert base_url() == DEFAULT_BASE_URL


def test_blank_api_key_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HIRO_API_KEY", "   ")
    assert api_key() is None
