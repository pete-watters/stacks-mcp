"""Token metadata resolution: the sBTC flag, decimals maths and the unknown fallback."""

from typing import Any

import respx

from stacks_mcp.clients.hiro import DEFAULT_BASE_URL, HiroClient, HiroFtMetadata
from stacks_mcp.tokens import (
    SBTC_CONTRACT_ID,
    build_token_balance,
    contract_name,
    has_unknown_decimals,
    resolve_metadata,
)

PIXELSTACKS = "SP14XEKF7G8Q4WFYBSE77XSDMM67GTVF95R4V680.pixelstacks"
TEIKO = "SP1T0VY3DNXRVP6HBM75DFWW0199CR0X15PC1D81B.teiko-token-stxcity"


def test_sbtc_contract_is_flagged() -> None:
    token = build_token_balance(SBTC_CONTRACT_ID, "129", HiroFtMetadata(symbol="sBTC", decimals=8))
    assert token.is_sbtc
    assert token.symbol == "sBTC"
    assert token.decimals == 8
    assert token.balance_raw == "129"
    assert token.balance == "0.00000129"


def test_other_contracts_are_not_sbtc() -> None:
    token = build_token_balance(TEIKO, "10000000", HiroFtMetadata(symbol="Teiko", decimals=6))
    assert not token.is_sbtc
    assert token.balance == "10.000000"


def test_unknown_metadata_falls_back_to_contract_name_and_base_units() -> None:
    token = build_token_balance(PIXELSTACKS, "999000000", None)
    assert token.symbol == "pixelstacks"
    assert token.decimals == 0
    assert token.balance == "999000000"
    assert has_unknown_decimals(None)


def test_metadata_without_decimals_keeps_base_units() -> None:
    """Recorded case: rALEX has a symbol but no decimals."""
    metadata = HiroFtMetadata(symbol="alexdao.org", decimals=None)
    token = build_token_balance(
        "SP37WN2BYHKZ90T1ATHTCNG8EFYHS3B49KNGS02ZK.RALEX", "154000", metadata
    )
    assert token.symbol == "alexdao.org"
    assert token.decimals == 0
    assert token.balance == "154000"
    assert has_unknown_decimals(metadata)


def test_contract_name_split() -> None:
    assert contract_name(SBTC_CONTRACT_ID) == "sbtc-token"
    assert contract_name("no-dot") == "no-dot"


async def test_metadata_is_fetched_once_per_process(
    mocked_http: respx.MockRouter, ft_metadata_fixtures: dict[str, Any]
) -> None:
    route = mocked_http.get(f"{DEFAULT_BASE_URL}/metadata/v1/ft/{TEIKO}").respond(
        200, json=ft_metadata_fixtures[TEIKO]
    )
    client = HiroClient()
    try:
        first = await resolve_metadata(client, TEIKO)
        second = await resolve_metadata(client, TEIKO)
    finally:
        await client.aclose()
    assert route.call_count == 1
    assert first is not None and first.symbol == "Teiko"
    assert second is first


async def test_missing_metadata_is_cached_too(mocked_http: respx.MockRouter) -> None:
    route = mocked_http.get(f"{DEFAULT_BASE_URL}/metadata/v1/ft/{PIXELSTACKS}").respond(
        404, json={"error": "Token not found"}
    )
    client = HiroClient()
    try:
        assert await resolve_metadata(client, PIXELSTACKS) is None
        assert await resolve_metadata(client, PIXELSTACKS) is None
    finally:
        await client.aclose()
    assert route.call_count == 1
