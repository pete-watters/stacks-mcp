"""MCP application and tool registration."""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from stacks_mcp import __version__
from stacks_mcp.clients.hiro import get_client as get_hiro_client
from stacks_mcp.clients.mempool import get_client
from stacks_mcp.errors import InvalidAddressError, UpstreamError
from stacks_mcp.models import (
    BtcBalance,
    Chain,
    RecentTransactions,
    StxBalance,
    TokenBalance,
    TokenBalances,
    TransactionSummary,
)
from stacks_mcp.tokens import build_token_balance, has_unknown_decimals, resolve_metadata
from stacks_mcp.transactions import btc_transaction_summary, stx_transaction_summary
from stacks_mcp.validation import validate_btc_address, validate_stx_principal

MAX_TRANSACTION_LIMIT = 50

mcp = MCPServer(
    "stacks-mcp",
    instructions=(
        "Read-only Bitcoin and Stacks chain data. Tools never hold keys, sign or broadcast."
    ),
    version=__version__,
)


@mcp.tool()
async def get_btc_balance(address: str) -> BtcBalance:
    """Get the current balance of a Bitcoin mainnet address.

    Call this when the user asks how much BTC an address holds, whether an
    address has any unconfirmed activity, or how many transactions it has
    seen. Accepts legacy (1...), P2SH (3...) and bech32 (bc1...) addresses.

    Returns confirmed and unconfirmed balances in satoshis, the confirmed
    balance in BTC (8 decimal places), the confirmed transaction count and a
    one-sentence summary. Data comes from mempool.space and is read-only:
    this tool never holds keys, signs or broadcasts anything.
    """
    try:
        clean = validate_btc_address(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        raw = await get_client().get_address(clean)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc
    return BtcBalance.build(
        address=raw.address,
        confirmed_sats=raw.chain_stats.balance_sats,
        unconfirmed_sats=raw.mempool_stats.balance_sats,
        tx_count=raw.chain_stats.tx_count,
    )


@mcp.tool()
async def get_stx_balance(address: str) -> StxBalance:
    """Get the STX balance of a Stacks mainnet principal.

    Call this when the user asks how much STX an address holds, how much of it
    is locked by stacking, or what its next nonce is. Accepts standard
    principals (SP... or SM...) and contract principals (SP....contract-name).

    Returns the total balance in micro-STX and STX (6 decimal places), the
    locked amount in both units, the next usable nonce and a one-sentence
    summary. Data comes from the Hiro API and is read-only: this tool never
    holds keys, signs or broadcasts anything.
    """
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    client = get_hiro_client()
    try:
        balance, nonces = await asyncio.gather(
            client.get_stx_balance(principal), client.get_nonces(principal)
        )
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc
    return StxBalance.build(
        address=principal,
        balance_ustx=balance.balance_ustx,
        locked_ustx=balance.locked_ustx,
        nonce=nonces.next_nonce,
    )


@mcp.tool()
async def get_token_balances(address: str) -> TokenBalances:
    """List the SIP-10 fungible tokens a Stacks mainnet principal holds.

    Call this when the user asks about token positions, sBTC holdings, or what
    a Stacks address owns beyond STX. Accepts standard principals (SP... or
    SM...) and contract principals (SP....contract-name).

    Each position gives the token contract id, its symbol and decimals, the
    balance in base units and the same balance scaled for humans, plus an
    `is_sbtc` flag for the mainnet sBTC contract. When a token's metadata is
    unknown the symbol falls back to the contract name, decimals to 0, and the
    balance stays in base units; the summary says how many are affected. Data
    comes from the Hiro API and is read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    client = get_hiro_client()
    try:
        positions = await client.get_ft_balances(principal)
        tokens: list[TokenBalance] = []
        unknown = 0
        for position in positions.results:
            metadata = await resolve_metadata(client, position.contract_id)
            unknown += 1 if has_unknown_decimals(metadata) else 0
            tokens.append(build_token_balance(position.contract_id, position.balance, metadata))
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc
    return TokenBalances.build(address=principal, tokens=tokens, unknown=unknown)


@mcp.tool()
async def get_recent_transactions(
    address: str, chain: Chain, limit: int = 10
) -> RecentTransactions:
    """List recent transactions of a Bitcoin or Stacks address, newest first.

    Call this when the user asks what an address has been doing lately, who it
    paid, or whether anything is pending. Set `chain` to "btc" for a Bitcoin
    address (1..., 3... or bc1...) or "stx" for a Stacks principal (SP..., SM...
    or SP....contract-name). `limit` is 1 to 50 and defaults to 10.

    Each entry gives the transaction id, block time as ISO 8601 UTC (null while
    unconfirmed), the direction as seen by the queried address ("in", "out",
    "self" or "other"), the amount in BTC or STX, the counterparty address or
    contract id, the status and what the transaction did. Bitcoin data comes
    from mempool.space and Stacks data from the Hiro API, which returns
    confirmed transactions only. Read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    if limit < 1 or limit > MAX_TRANSACTION_LIMIT:
        raise ToolError(f"limit must be between 1 and {MAX_TRANSACTION_LIMIT}, got {limit}")
    summaries: list[TransactionSummary]
    if chain == "btc":
        try:
            clean = validate_btc_address(address)
        except InvalidAddressError as exc:
            raise ToolError(str(exc)) from exc
        try:
            txs = await get_client().get_address_txs(clean)
        except UpstreamError as exc:
            raise ToolError(str(exc)) from exc
        summaries = [btc_transaction_summary(tx, clean) for tx in txs[:limit]]
        return RecentTransactions.build(address=clean, chain=chain, transactions=summaries)
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        page = await get_hiro_client().get_transactions(principal, limit)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc
    summaries = [stx_transaction_summary(item, principal) for item in page.results]
    return RecentTransactions.build(address=principal, chain=chain, transactions=summaries)


def main() -> None:
    """Run the server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
