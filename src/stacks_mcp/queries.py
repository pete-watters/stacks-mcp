"""Upstream reads composed into the output models the tools return.

One function per answer. Each makes the requests that answer needs and returns a
finished model, so a tool and the address-summary resource read the same code
rather than two copies of it.

``UpstreamError`` escapes rather than being handled here: a tool turns it into a
``ToolError``, while the snapshot records it as a named failure and keeps going.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from stacks_mcp.clients.hiro import get_client as get_hiro_client
from stacks_mcp.clients.mempool import get_client as get_mempool_client
from stacks_mcp.models import (
    AddressSummary,
    BtcBalance,
    FeeOption,
    FeePriority,
    RecentTransactions,
    StxBalance,
    StxTransferDraft,
    SummaryFailure,
    TokenBalance,
    TokenBalances,
    TransactionSummary,
    ustx_to_stx,
)
from stacks_mcp.tokens import build_token_balance, has_unknown_decimals, resolve_metadata
from stacks_mcp.transactions import btc_transaction_summary, stx_transaction_summary

# How many transactions the snapshot carries. The same default the
# `get_recent_transactions` tool uses: enough to see the shape of recent
# activity, small enough that the resource stays one cheap read.
SUMMARY_TRANSACTION_LIMIT = 10


async def fetch_btc_balance(address: str) -> BtcBalance:
    """Read the confirmed and mempool balance of a Bitcoin address."""
    raw = await get_mempool_client().get_address(address)
    return BtcBalance.build(
        address=raw.address,
        confirmed_sats=raw.chain_stats.balance_sats,
        unconfirmed_sats=raw.mempool_stats.balance_sats,
        tx_count=raw.chain_stats.tx_count,
    )


async def fetch_btc_transactions(address: str, limit: int) -> RecentTransactions:
    """Read the newest transactions of a Bitcoin address, unconfirmed first."""
    txs = await get_mempool_client().get_address_txs(address)
    summaries = [btc_transaction_summary(tx, address) for tx in txs[:limit]]
    return RecentTransactions.build(address=address, chain="btc", transactions=summaries)


async def fetch_stx_balance(principal: str) -> StxBalance:
    """Read the STX balance, lock state and next nonce of a Stacks principal.

    Balance and nonce are two endpoints, so they go out together.
    """
    client = get_hiro_client()
    balance, nonces = await asyncio.gather(
        client.get_stx_balance(principal), client.get_nonces(principal)
    )
    return StxBalance.build(
        address=principal,
        balance_ustx=balance.balance_ustx,
        locked_ustx=balance.locked_ustx,
        nonce=nonces.next_nonce,
    )


async def fetch_token_balances(principal: str) -> TokenBalances:
    """Read every SIP-10 position of a Stacks principal, with its metadata.

    Metadata is one request per token contract, cached for the process, so a
    second address holding the same token costs nothing.
    """
    client = get_hiro_client()
    positions = await client.get_ft_balances(principal)
    tokens: list[TokenBalance] = []
    unknown = 0
    for position in positions.results:
        metadata = await resolve_metadata(client, position.contract_id)
        unknown += 1 if has_unknown_decimals(metadata) else 0
        tokens.append(build_token_balance(position.contract_id, position.balance, metadata))
    return TokenBalances.build(address=principal, tokens=tokens, unknown=unknown)


async def fetch_stx_transactions(principal: str, limit: int) -> RecentTransactions:
    """Read the newest confirmed transactions of a Stacks principal."""
    page = await get_hiro_client().get_transactions(principal, limit)
    summaries: list[TransactionSummary] = [
        stx_transaction_summary(item, principal) for item in page.results
    ]
    return RecentTransactions.build(address=principal, chain="stx", transactions=summaries)


async def fetch_stx_transfer_draft(
    sender: str, recipient: str, amount_ustx: int, memo: str | None
) -> StxTransferDraft:
    """Assemble an unsigned STX transfer: the sender's nonce and balance, plus fees.

    Nothing is signed here and no key is read. The nonce and balance come from
    the sender's account and the fee tiers from the mempool, so a wallet has
    every input it needs to build the transaction itself.
    """
    client = get_hiro_client()
    balance, nonces, fees = await asyncio.gather(
        client.get_stx_balance(sender), client.get_nonces(sender), client.get_mempool_fees()
    )
    tiers = fees.token_transfer
    by_priority: list[tuple[FeePriority, int]] = [
        ("no_priority", tiers.no_priority),
        ("low_priority", tiers.low_priority),
        ("medium_priority", tiers.medium_priority),
        ("high_priority", tiers.high_priority),
    ]
    options = [
        FeeOption(priority=priority, fee_ustx=fee_ustx, fee_stx=ustx_to_stx(fee_ustx))
        for priority, fee_ustx in by_priority
    ]
    return StxTransferDraft.build(
        sender=sender,
        recipient=recipient,
        amount_ustx=amount_ustx,
        memo=memo,
        nonce=nonces.next_nonce,
        fees=options,
        balance_ustx=balance.balance_ustx,
    )


def _kept[ModelT: BaseModel](
    part: str, result: ModelT | BaseException, failures: list[SummaryFailure]
) -> ModelT | None:
    """Keep a successful read, or record why it failed and return nothing.

    ``asyncio.gather(return_exceptions=True)`` also captures cancellation, which
    is not this snapshot's failure to report, so anything that is not an
    ``Exception`` is re-raised.
    """
    if not isinstance(result, BaseException):
        return result
    if not isinstance(result, Exception):
        raise result
    failures.append(SummaryFailure(part=part, reason=str(result)))
    return None


async def fetch_address_summary(principal: str) -> AddressSummary:
    """Read a Stacks principal's STX, tokens and recent transactions in one pass.

    The three reads run concurrently and independently. One upstream failure
    costs that part alone: the snapshot returns what it could read and names
    what it could not, rather than raising and losing the rest.
    """
    stx, tokens, transactions = await asyncio.gather(
        fetch_stx_balance(principal),
        fetch_token_balances(principal),
        fetch_stx_transactions(principal, SUMMARY_TRANSACTION_LIMIT),
        return_exceptions=True,
    )
    failures: list[SummaryFailure] = []
    kept_stx = _kept("STX balance", stx, failures)
    kept_tokens = _kept("token balances", tokens, failures)
    kept_transactions = _kept("recent transactions", transactions, failures)
    return AddressSummary.build(
        address=principal,
        stx=kept_stx,
        tokens=kept_tokens,
        transactions=kept_transactions,
        failures=failures,
    )
