from typing import Any

import httpx
import pytest
import respx

from stacks_mcp.clients.mempool import DEFAULT_BASE_URL, MempoolClient, base_url
from stacks_mcp.errors import UpstreamError

GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


async def test_get_address_parses_fixture(
    mocked_http: respx.MockRouter, genesis_fixture: dict[str, Any]
) -> None:
    route = mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(
        200, json=genesis_fixture
    )
    client = MempoolClient()
    try:
        result = await client.get_address(GENESIS)
    finally:
        await client.aclose()

    assert route.called
    assert result.address == GENESIS
    assert result.chain_stats.funded_txo_sum == 5747023635
    assert result.chain_stats.spent_txo_sum == 0
    assert result.chain_stats.balance_sats == 5747023635
    assert result.chain_stats.tx_count == 65805
    assert result.mempool_stats.balance_sats == 4218
    assert result.mempool_stats.tx_count == 2


async def test_sends_user_agent(
    mocked_http: respx.MockRouter, genesis_fixture: dict[str, Any]
) -> None:
    route = mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(
        200, json=genesis_fixture
    )
    client = MempoolClient()
    try:
        await client.get_address(GENESIS)
    finally:
        await client.aclose()
    request = route.calls.last.request
    assert request.headers["User-Agent"].startswith("stacks-mcp/")


@pytest.mark.parametrize("status", [500, 502, 503, 404, 429])
async def test_non_2xx_raises_upstream_error(mocked_http: respx.MockRouter, status: int) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(status, text="nope")
    client = MempoolClient()
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await client.get_address(GENESIS)
    finally:
        await client.aclose()
    assert excinfo.value.status_code == status
    assert excinfo.value.service == "mempool.space"
    assert "nope" in str(excinfo.value)


async def test_transport_error_raises_upstream_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").mock(
        side_effect=httpx.ConnectTimeout("timed out")
    )
    client = MempoolClient()
    try:
        with pytest.raises(UpstreamError) as excinfo:
            await client.get_address(GENESIS)
    finally:
        await client.aclose()
    assert excinfo.value.status_code is None


async def test_unexpected_body_raises_upstream_error(mocked_http: respx.MockRouter) -> None:
    mocked_http.get(f"{DEFAULT_BASE_URL}/address/{GENESIS}").respond(200, json={"foo": 1})
    client = MempoolClient()
    try:
        with pytest.raises(UpstreamError):
            await client.get_address(GENESIS)
    finally:
        await client.aclose()


def test_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMPOOL_BASE_URL", "http://localhost:8999/api/")
    assert base_url() == "http://localhost:8999/api"
    monkeypatch.delenv("MEMPOOL_BASE_URL")
    assert base_url() == DEFAULT_BASE_URL
