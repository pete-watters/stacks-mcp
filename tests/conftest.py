"""Shared fixtures. Every test runs with HTTP fully mocked; unmocked calls fail."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx

from stacks_mcp.tokens import clear_metadata_cache

FIXTURES = Path(__file__).parent / "fixtures"

# Recorded from mainnet. The deployer of the sBTC contracts: active, holds STX
# and four fungible tokens including sBTC itself.
SBTC_DEPLOYER = "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4"
GENESIS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"


def load_fixture(*parts: str) -> Any:
    return json.loads(FIXTURES.joinpath(*parts).read_text())


@pytest.fixture(autouse=True)
def mocked_http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


@pytest.fixture(autouse=True)
def empty_token_cache() -> Iterator[None]:
    clear_metadata_cache()
    yield
    clear_metadata_cache()


@pytest.fixture
def genesis_fixture() -> Any:
    return load_fixture("mempool", "address_genesis.json")


@pytest.fixture
def genesis_txs_fixture() -> Any:
    return load_fixture("mempool", "address_genesis_txs.json")


@pytest.fixture
def stx_balance_fixture() -> Any:
    return load_fixture("hiro", "v3_stx_balance_sbtc_deployer.json")


@pytest.fixture
def nonces_fixture() -> Any:
    return load_fixture("hiro", "v3_nonces_sbtc_deployer.json")


@pytest.fixture
def ft_balances_fixture() -> Any:
    return load_fixture("hiro", "v3_ft_balances_sbtc_deployer.json")


@pytest.fixture
def stx_transactions_fixture() -> Any:
    return load_fixture("hiro", "v3_transactions_sbtc_deployer.json")


@pytest.fixture
def ft_metadata_fixtures() -> dict[str, Any]:
    """Metadata keyed by contract id, as recorded for the deployer's four tokens."""
    return {
        "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token": load_fixture(
            "hiro", "metadata_ft_sbtc.json"
        ),
        "SP1T0VY3DNXRVP6HBM75DFWW0199CR0X15PC1D81B.teiko-token-stxcity": load_fixture(
            "hiro", "metadata_ft_teiko.json"
        ),
        "SP37WN2BYHKZ90T1ATHTCNG8EFYHS3B49KNGS02ZK.RALEX": load_fixture(
            "hiro", "metadata_ft_ralex.json"
        ),
        # Recorded as a 404 body: the indexer has no metadata for this token.
        "SP14XEKF7G8Q4WFYBSE77XSDMM67GTVF95R4V680.pixelstacks": load_fixture(
            "hiro", "metadata_ft_pixelstacks.json"
        ),
    }
