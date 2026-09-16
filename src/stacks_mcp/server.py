"""MCP application and tool registration."""

from __future__ import annotations

import asyncio

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from stacks_mcp import __version__
from stacks_mcp.clients.hiro import HiroTransactionEvent
from stacks_mcp.clients.hiro import get_client as get_hiro_client
from stacks_mcp.clients.mempool import get_client
from stacks_mcp.decoders.btc import decode_btc_transaction
from stacks_mcp.decoders.stacks import decode_stacks_transaction
from stacks_mcp.errors import InvalidAddressError, InvalidTxidError, UpstreamError
from stacks_mcp.models import (
    BtcBalance,
    Chain,
    RecentTransactions,
    StxBalance,
    TokenBalance,
    TokenBalances,
    TransactionExplanation,
    TransactionSummary,
)
from stacks_mcp.tokens import build_token_balance, has_unknown_decimals, resolve_metadata
from stacks_mcp.transactions import btc_transaction_summary, stx_transaction_summary
from stacks_mcp.validation import validate_btc_address, validate_stx_principal, validate_txid

MAX_TRANSACTION_LIMIT = 50
NOT_FOUND = 404

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


def _transaction_error(exc: UpstreamError, chain: Chain, txid: str) -> str:
    """Turn an upstream failure into something a caller can act on.

    A 404 means the id is well formed but no such transaction exists, which is a
    different problem from the API being down, so it gets its own wording.
    """
    if exc.status_code == NOT_FOUND:
        label = "Bitcoin" if chain == "btc" else "Stacks"
        return f"no {label} transaction found with id {txid}"
    return str(exc)


@mcp.tool()
async def explain_transaction(txid: str, chain: Chain) -> TransactionExplanation:
    """Explain one Bitcoin or Stacks transaction in plain English.

    Call this when the user asks what a transaction did, what a txid means, or
    to check whether a transfer, a stacking lock or an sBTC deposit went
    through. Set `chain` to "btc" or "stx". A txid is 64 hex characters, with or
    without a `0x` prefix on Stacks.

    Decoding is deterministic and total: it is a table of rules, not a language
    model, so the same transaction always gives the same answer, and an
    unrecognised shape still returns a structured summary rather than an error.
    Stacks cases decoded by name: STX transfer, SIP-10 and sBTC transfer, sBTC
    deposit and withdrawal, pox stacking (`stack-stx`, `delegate-stx`,
    `stack-increase`), contract call, contract deploy, coinbase and tenure
    change. Bitcoin cases: simple transfer, consolidation, batch payment,
    self-send and coinbase, with an OP_RETURN noted where present.

    Returns `kind` (which case matched), `summary` (the sentence), `detail` (the
    decoded specifics), `fee` (sat/vB on Bitcoin, STX and uSTX on Stacks),
    `status`, `block_height`, `timestamp` and `participants` (addresses and
    contracts with a role each). Bitcoin data comes from mempool.space and
    Stacks data from the Hiro API. Read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    try:
        clean = validate_txid(txid, chain)
    except InvalidTxidError as exc:
        raise ToolError(str(exc)) from exc
    if chain == "btc":
        try:
            btc_tx = await get_client().get_transaction(clean)
        except UpstreamError as exc:
            raise ToolError(_transaction_error(exc, chain, clean)) from exc
        return decode_btc_transaction(btc_tx)
    client = get_hiro_client()
    try:
        stx_tx = await client.get_transaction(clean)
        events: list[HiroTransactionEvent] = []
        # Events are a second request, so only ask when a contract call has any.
        # Nothing else this decoder handles needs them.
        if stx_tx.type == "contract_call" and stx_tx.event_count > 0:
            events = (await client.get_transaction_events(clean)).results
    except UpstreamError as exc:
        raise ToolError(_transaction_error(exc, chain, clean)) from exc
    return decode_stacks_transaction(stx_tx, events)


def main() -> None:
    """Run the server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
