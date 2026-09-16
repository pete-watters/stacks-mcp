"""Async client for the Hiro Stacks Blockchain API and Token Metadata API.

Endpoints and response shapes were checked against the published OpenAPI specs
(``stacks-blockchain-api`` 9.3.0, ``token-metadata-api`` 2.3.1, both served from
``https://api.hiro.so/``) and against recorded mainnet responses under
``tests/fixtures/hiro/``.

The ``/extended/v1`` and ``/extended/v2`` address endpoints still answer, but
every response carries ``warning: 299 - "Deprecated"``. The ``/extended/v3``
``principals`` endpoints are the current ones, so this client uses those.
"""

from __future__ import annotations

import os
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from stacks_mcp import __version__
from stacks_mcp.errors import UpstreamError

DEFAULT_BASE_URL = "https://api.hiro.so"
SERVICE = "Hiro API"
USER_AGENT = f"stacks-mcp/{__version__} (+https://github.com/pete-watters/stacks-mcp)"
TIMEOUT_SECONDS = 15.0

# Metadata is missing for tokens the indexer has not processed (404) or is still
# processing (422). Both are normal and must not fail a balance query.
_SOFT_METADATA_STATUSES = frozenset({404, 422})

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class StxLock(BaseModel):
    """The locked (stacked) portion of an STX balance."""

    amount: str
    lock_tx_id: str | None = None
    burn_unlock_height: int | None = None


class HiroStxBalance(BaseModel):
    """Response of ``GET /extended/v3/principals/{principal}/balances/stx``."""

    balance: str
    available: str
    locked: StxLock | None = None

    @property
    def balance_ustx(self) -> int:
        return int(self.balance)

    @property
    def locked_ustx(self) -> int:
        return int(self.locked.amount) if self.locked is not None else 0


class HiroNonces(BaseModel):
    """Response of ``GET /extended/v3/principals/{principal}/nonces``."""

    next_nonce: int
    last_confirmed_nonce: int


class HiroFtPosition(BaseModel):
    """One fungible-token position: ``contract.name::asset`` and a base-unit balance."""

    asset_identifier: str
    balance: str

    @property
    def contract_id(self) -> str:
        """The ``SP....token-name`` part of the asset identifier."""
        return self.asset_identifier.split("::", 1)[0]


class HiroFtBalances(BaseModel):
    """Response of ``GET /extended/v3/principals/{principal}/balances/ft``."""

    total: int
    results: list[HiroFtPosition]


class HiroFtMetadata(BaseModel):
    """Response of ``GET /metadata/v1/ft/{principal}``. Every field is optional."""

    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None
    asset_identifier: str | None = None


class HiroBlock(BaseModel):
    """The block a transaction was mined in."""

    height: int
    time: int


class HiroTxSender(BaseModel):
    address: str
    nonce: int


class HiroTokenTransfer(BaseModel):
    recipient: str
    amount: str


class HiroContractCall(BaseModel):
    contract_id: str
    function_name: str


class HiroSmartContract(BaseModel):
    contract_id: str


class HiroCoinbase(BaseModel):
    alt_recipient: str | None = None


class HiroTransaction(BaseModel):
    """A transaction summary. One of the ``token_transfer``/``contract_call``/
    ``smart_contract``/``coinbase`` blocks is present, chosen by ``type``."""

    tx_id: str
    sender: HiroTxSender
    fee_rate: str
    block: HiroBlock
    status: str
    type: str
    token_transfer: HiroTokenTransfer | None = None
    contract_call: HiroContractCall | None = None
    smart_contract: HiroSmartContract | None = None
    coinbase: HiroCoinbase | None = None


class HiroStxBalanceChange(BaseModel):
    """STX moved by one transaction. ``sent`` includes the transaction fee."""

    sent: str
    received: str
    net: str


class HiroBalanceChanges(BaseModel):
    stx: HiroStxBalanceChange


class HiroPrincipalTransaction(BaseModel):
    """One item of ``GET /extended/v3/principals/{principal}/transactions``."""

    transaction: HiroTransaction
    involvement: str
    balance_changes: HiroBalanceChanges


class HiroPrincipalTransactions(BaseModel):
    total: int
    results: list[HiroPrincipalTransaction]


def base_url() -> str:
    """Base URL for the API, overridable with ``HIRO_BASE_URL``."""
    return os.environ.get("HIRO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def api_key() -> str | None:
    """Optional ``HIRO_API_KEY``, sent as ``x-api-key`` to raise rate limits."""
    key = os.environ.get("HIRO_API_KEY", "").strip()
    return key or None


class HiroClient:
    """Thin wrapper over one shared ``httpx.AsyncClient``."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> httpx.Response:
        key = api_key()
        headers = {"x-api-key": key} if key else None
        try:
            return await self._http.get(f"{base_url()}{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamError(SERVICE, None, str(exc)) from exc

    async def _get_json(
        self,
        path: str,
        model: type[_ModelT],
        params: dict[str, str | int] | None = None,
    ) -> _ModelT:
        response = await self._get(path, params)
        if response.status_code < 200 or response.status_code >= 300:
            raise UpstreamError(SERVICE, response.status_code, response.text.strip()[:200])
        try:
            return model.model_validate_json(response.content)
        except ValidationError as exc:
            raise UpstreamError(SERVICE, response.status_code, f"unexpected body: {exc}") from exc

    async def get_stx_balance(self, principal: str) -> HiroStxBalance:
        """Fetch the total, available and locked micro-STX of a principal."""
        return await self._get_json(
            f"/extended/v3/principals/{principal}/balances/stx", HiroStxBalance
        )

    async def get_nonces(self, principal: str) -> HiroNonces:
        """Fetch the confirmed and next nonce of a principal."""
        return await self._get_json(f"/extended/v3/principals/{principal}/nonces", HiroNonces)

    async def get_ft_balances(self, principal: str, limit: int = 200) -> HiroFtBalances:
        """Fetch fungible-token positions, sorted by balance descending."""
        return await self._get_json(
            f"/extended/v3/principals/{principal}/balances/ft",
            HiroFtBalances,
            params={"limit": limit},
        )

    async def get_transactions(self, principal: str, limit: int) -> HiroPrincipalTransactions:
        """Fetch confirmed transactions that a principal sent, sponsored or was affected by."""
        return await self._get_json(
            f"/extended/v3/principals/{principal}/transactions",
            HiroPrincipalTransactions,
            params={"limit": limit},
        )

    async def get_ft_metadata(self, contract_id: str) -> HiroFtMetadata | None:
        """Fetch SIP-010 metadata for a token contract.

        Returns ``None`` when the indexer has no metadata yet (404) or is still
        fetching it (422). Any other non-2xx raises ``UpstreamError``.
        """
        response = await self._get(f"/metadata/v1/ft/{contract_id}")
        if response.status_code in _SOFT_METADATA_STATUSES:
            return None
        if response.status_code < 200 or response.status_code >= 300:
            raise UpstreamError(SERVICE, response.status_code, response.text.strip()[:200])
        try:
            return HiroFtMetadata.model_validate_json(response.content)
        except ValidationError:
            return None


_client: HiroClient | None = None


def get_client() -> HiroClient:
    """Process-wide client so every tool call shares one connection pool."""
    global _client
    if _client is None:
        _client = HiroClient()
    return _client
