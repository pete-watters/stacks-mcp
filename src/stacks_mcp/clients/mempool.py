"""Async client for the mempool.space REST API.

Endpoint shapes were checked against https://mempool.space/docs/api/rest and a
recorded mainnet response (``tests/fixtures/mempool/address_genesis.json``).
"""

from __future__ import annotations

import os

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

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


class MempoolTxStatus(BaseModel):
    """Confirmation state of a transaction. Unconfirmed ones carry no block."""

    confirmed: bool
    block_height: int | None = None
    block_time: int | None = None


class MempoolPrevout(BaseModel):
    """The output an input spends. Absent on coinbase inputs."""

    scriptpubkey_address: str | None = None
    value: int = 0


class MempoolVin(BaseModel):
    is_coinbase: bool = False
    prevout: MempoolPrevout | None = None


class MempoolVout(BaseModel):
    scriptpubkey_address: str | None = None
    value: int = 0


class MempoolTransaction(BaseModel):
    """One item of ``GET /api/address/{address}/txs``."""

    txid: str
    fee: int = 0
    status: MempoolTxStatus
    vin: list[MempoolVin]
    vout: list[MempoolVout]

    @property
    def is_coinbase(self) -> bool:
        return any(vin.is_coinbase for vin in self.vin)

    def value_sent_by(self, address: str) -> int:
        """Total satoshis this transaction spends out of ``address``."""
        return sum(
            vin.prevout.value
            for vin in self.vin
            if vin.prevout is not None and vin.prevout.scriptpubkey_address == address
        )

    def value_received_by(self, address: str) -> int:
        """Total satoshis this transaction pays to ``address``."""
        return sum(out.value for out in self.vout if out.scriptpubkey_address == address)

    def counterparty_for(self, address: str) -> str | None:
        """The most plausible other party: a funding input, else a paid output."""
        for vin in self.vin:
            if vin.prevout is None:
                continue
            candidate = vin.prevout.scriptpubkey_address
            if candidate is not None and candidate != address:
                return candidate
        for out in self.vout:
            if out.scriptpubkey_address is not None and out.scriptpubkey_address != address:
                return out.scriptpubkey_address
        return None


# ``/txs`` answers with a bare JSON array, so it needs an adapter rather than a model.
_TX_LIST = TypeAdapter(list[MempoolTransaction])


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

    async def _get(self, path: str) -> httpx.Response:
        try:
            response = await self._http.get(f"{base_url()}{path}")
        except httpx.HTTPError as exc:
            raise UpstreamError(SERVICE, None, str(exc)) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise UpstreamError(SERVICE, response.status_code, response.text.strip()[:200])
        return response

    async def get_address(self, address: str) -> MempoolAddress:
        """Fetch confirmed and mempool stats for a Bitcoin address."""
        response = await self._get(f"/address/{address}")
        try:
            return MempoolAddress.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(SERVICE, response.status_code, f"unexpected body: {exc}") from exc

    async def get_address_txs(self, address: str) -> list[MempoolTransaction]:
        """Fetch the newest transactions of an address, unconfirmed ones first.

        ``GET /api/address/{address}/txs`` returns up to 50 mempool transactions
        plus the first 25 confirmed ones. This client reads only that first page.
        """
        response = await self._get(f"/address/{address}/txs")
        try:
            return _TX_LIST.validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(SERVICE, response.status_code, f"unexpected body: {exc}") from exc


_client: MempoolClient | None = None


def get_client() -> MempoolClient:
    """Process-wide client so every tool call shares one connection pool."""
    global _client
    if _client is None:
        _client = MempoolClient()
    return _client
