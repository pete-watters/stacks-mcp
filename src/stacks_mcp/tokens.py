"""SIP-010 token metadata: resolution, a process-wide cache and the sBTC check."""

from __future__ import annotations

from stacks_mcp.clients.hiro import HiroClient, HiroFtMetadata
from stacks_mcp.models import TokenBalance, base_units_to_amount

# Mainnet sBTC. Verified against https://api.hiro.so/metadata/v1/ft/<id>, which
# answers name "sBTC", symbol "sBTC", decimals 8, and against the same contract
# id used as the fungible-token example in Hiro's own OpenAPI spec.
SBTC_CONTRACT_ID = "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token"

_metadata_cache: dict[str, HiroFtMetadata | None] = {}


def contract_name(contract_id: str) -> str:
    """The ``token-name`` half of ``SP....token-name``."""
    _, _, name = contract_id.partition(".")
    return name or contract_id


async def resolve_metadata(client: HiroClient, contract_id: str) -> HiroFtMetadata | None:
    """Fetch token metadata once per process, caching misses as well as hits."""
    if contract_id not in _metadata_cache:
        _metadata_cache[contract_id] = await client.get_ft_metadata(contract_id)
    return _metadata_cache[contract_id]


def clear_metadata_cache() -> None:
    """Drop the cache. Used by tests; harmless at runtime."""
    _metadata_cache.clear()


def build_token_balance(
    contract_id: str, balance_raw: str, metadata: HiroFtMetadata | None
) -> TokenBalance:
    """Combine a raw balance with metadata, falling back when metadata is missing.

    An unknown token keeps its base-unit balance: symbol becomes the contract
    name and decimals 0, so no amount is silently misscaled.
    """
    symbol = metadata.symbol if metadata is not None and metadata.symbol else None
    decimals = metadata.decimals if metadata is not None and metadata.decimals is not None else 0
    return TokenBalance(
        contract_id=contract_id,
        symbol=symbol or contract_name(contract_id),
        decimals=decimals,
        balance_raw=balance_raw,
        balance=base_units_to_amount(int(balance_raw), decimals),
        is_sbtc=contract_id == SBTC_CONTRACT_ID,
    )


def has_unknown_decimals(metadata: HiroFtMetadata | None) -> bool:
    """True when a balance can only be shown in base units."""
    return metadata is None or metadata.decimals is None
