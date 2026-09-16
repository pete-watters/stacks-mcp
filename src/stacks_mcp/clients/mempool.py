"""Async client for the mempool.space REST API.

Endpoint shapes were checked against https://mempool.space/docs/api/rest and a
recorded mainnet response (``tests/fixtures/mempool/address_genesis.json``).
"""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, ValidationError

from stacks_mcp import __version__
from stacks_mcp.errors import UpstreamError

DEFAULT_BASE_URL = "https://mempool.space/api"
SERVICE = "mempool.space"
USER_AGENT = f"stacks-mcp/{__version__} (+https://github.com/pete-watters/stacks-mcp)"
TIMEOUT_SECONDS = 15.0


class MempoolAddressStats(BaseModel):
    """One side of the address stats: either confirmed (chain) or mempool."""

    funded_txo_count: int
    funded_txo_sum: int
    spent_txo_count: int
    spent_txo_sum: int
    tx_count: int

    @property
    def balance_sats(self) -> int:
        return self.funded_txo_sum - self.spent_txo_sum


class MempoolAddress(BaseModel):
    """Raw response of ``GET /api/address/{address}``."""

    address: str
    chain_stats: MempoolAddressStats
    mempool_stats: MempoolAddressStats


def base_url() -> str:
    """Base URL for the API, overridable with ``MEMPOOL_BASE_URL``."""
    return os.environ.get("MEMPOOL_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


class MempoolClient:
    """Thin wrapper over one shared ``httpx.AsyncClient``."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_address(self, address: str) -> MempoolAddress:
        """Fetch confirmed and mempool stats for a Bitcoin address."""
        url = f"{base_url()}/address/{address}"
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamError(SERVICE, None, str(exc)) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise UpstreamError(SERVICE, response.status_code, response.text.strip()[:200])
        try:
            return MempoolAddress.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(SERVICE, response.status_code, f"unexpected body: {exc}") from exc


_client: MempoolClient | None = None


def get_client() -> MempoolClient:
    """Process-wide client so every tool call shares one connection pool."""
    global _client
    if _client is None:
        _client = MempoolClient()
    return _client
