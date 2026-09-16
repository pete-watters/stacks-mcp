"""Pydantic output models returned by tools. Every model carries a ``summary``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

SATS_PER_BTC = Decimal(100_000_000)
USTX_PER_STX = Decimal(1_000_000)

Chain = Literal["btc", "stx"]
Direction = Literal["in", "out", "self", "other"]
TxStatus = Literal["confirmed", "pending", "failed"]
TxKind = Literal[
    "transfer",
    "token_transfer",
    "contract_call",
    "smart_contract",
    "coinbase",
    "other",
]
# What `explain_transaction` decoded a transaction into. `coinbase` is the one
# case both chains share; every other member belongs to exactly one chain.
ExplainKind = Literal[
    "stx_transfer",
    "sip10_transfer",
    "sbtc_deposit",
    "sbtc_withdrawal",
    "stacking",
    "contract_call",
    "contract_deploy",
    "tenure_change",
    "btc_transfer",
    "consolidation",
    "batch_payment",
    "self_send",
    "coinbase",
    "unknown",
]
# Scalars only, so `detail` stays flat and survives a JSON-schema round trip.
DetailValue = bool | int | str | list[str] | None


def sats_to_btc(sats: int) -> str:
    """Format satoshis as a BTC string with exactly 8 decimal places."""
    return f"{Decimal(sats) / SATS_PER_BTC:.8f}"


def ustx_to_stx(ustx: int) -> str:
    """Format micro-STX as an STX string with exactly 6 decimal places."""
    return f"{Decimal(ustx) / USTX_PER_STX:.6f}"


def base_units_to_amount(raw: int, decimals: int) -> str:
    """Format a token's base units using its declared decimals.

    ``decimals`` of 0 returns the raw integer, which is also the fallback when
    a token's metadata is unknown.
    """
    if decimals <= 0:
        return str(raw)
    return f"{Decimal(raw) / (Decimal(10) ** decimals):.{decimals}f}"


def unix_to_iso(timestamp: int | None) -> str | None:
    """Format a unix timestamp as ISO 8601 UTC, or ``None`` if there is none."""
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace("+00:00", "Z")


def short_address(address: str) -> str:
    return address if len(address) <= 12 else f"{address[:6]}...{address[-4:]}"


class BtcBalance(BaseModel):
    """Balance of one Bitcoin address as seen by mempool.space."""

    address: str = Field(description="The Bitcoin address that was queried.")
    confirmed_sats: int = Field(description="Confirmed balance in satoshis.")
    unconfirmed_sats: int = Field(
        description="Net change from unconfirmed mempool transactions, in satoshis."
    )
    confirmed_btc: str = Field(description="Confirmed balance in BTC, 8 decimal places.")
    tx_count: int = Field(description="Number of confirmed transactions involving the address.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(
        cls, address: str, confirmed_sats: int, unconfirmed_sats: int, tx_count: int
    ) -> BtcBalance:
        confirmed_btc = sats_to_btc(confirmed_sats)
        summary = (
            f"{short_address(address)} holds {confirmed_btc} BTC across {tx_count:,} "
            f"transactions, {unconfirmed_sats:,} sats unconfirmed"
        )
        return cls(
            address=address,
            confirmed_sats=confirmed_sats,
            unconfirmed_sats=unconfirmed_sats,
            confirmed_btc=confirmed_btc,
            tx_count=tx_count,
            summary=summary,
        )


class StxBalance(BaseModel):
    """STX position of one Stacks principal as seen by the Hiro API."""

    address: str = Field(description="The Stacks principal that was queried.")
    balance_ustx: int = Field(description="Total balance in micro-STX, locked included.")
    balance_stx: str = Field(description="Total balance in STX, 6 decimal places.")
    locked_ustx: int = Field(description="Micro-STX locked by stacking, 0 if none.")
    locked_stx: str = Field(description="Locked balance in STX, 6 decimal places.")
    nonce: int = Field(description="Next usable nonce for this principal.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(cls, address: str, balance_ustx: int, locked_ustx: int, nonce: int) -> StxBalance:
        balance_stx = ustx_to_stx(balance_ustx)
        locked_stx = ustx_to_stx(locked_ustx)
        locked_part = "none locked" if locked_ustx == 0 else f"{locked_stx} STX locked by stacking"
        summary = (
            f"{short_address(address)} holds {balance_stx} STX, {locked_part}, next nonce {nonce}"
        )
        return cls(
            address=address,
            balance_ustx=balance_ustx,
            balance_stx=balance_stx,
            locked_ustx=locked_ustx,
            locked_stx=locked_stx,
            nonce=nonce,
            summary=summary,
        )


class TokenBalance(BaseModel):
    """One SIP-010 fungible-token position."""

    contract_id: str = Field(description="Token contract, formatted `SP....token-name`.")
    symbol: str = Field(
        description="Token symbol from its metadata, or the contract name when unknown."
    )
    decimals: int = Field(description="Decimals from metadata; 0 when metadata is unknown.")
    balance_raw: str = Field(description="Balance in base units, as an integer string.")
    balance: str = Field(description="Balance scaled by `decimals`, human-readable.")
    is_sbtc: bool = Field(description="True for the mainnet sBTC token contract.")


class TokenBalances(BaseModel):
    """Every fungible token a Stacks principal holds."""

    address: str = Field(description="The Stacks principal that was queried.")
    tokens: list[TokenBalance] = Field(description="Positions, largest base-unit balance first.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(cls, address: str, tokens: list[TokenBalance], unknown: int) -> TokenBalances:
        short = short_address(address)
        if not tokens:
            summary = f"{short} holds no fungible tokens"
            return cls(address=address, tokens=tokens, summary=summary)
        listed = ", ".join(f"{token.balance} {token.symbol}" for token in tokens[:3])
        more = "" if len(tokens) <= 3 else f" and {len(tokens) - 3} more"
        note = (
            "" if unknown == 0 else f"; metadata unknown for {unknown} of them, shown in base units"
        )
        summary = f"{short} holds {len(tokens)} fungible tokens: {listed}{more}{note}"
        return cls(address=address, tokens=tokens, summary=summary)


class TransactionSummary(BaseModel):
    """One transaction, normalised across Bitcoin and Stacks."""

    txid: str = Field(description="Transaction id.")
    chain: Chain = Field(description="`btc` or `stx`.")
    timestamp: str | None = Field(
        description="Block time as ISO 8601 UTC, or null while unconfirmed."
    )
    direction: Direction = Field(
        description="`in`, `out`, `self` (both sides) or `other` (no value moved)."
    )
    amount: str = Field(description="Value moved, in BTC or STX. `0` when nothing moved.")
    counterparty: str | None = Field(description="Other address or contract id, if there is one.")
    status: TxStatus = Field(description="`confirmed`, `pending` or `failed`.")
    kind: TxKind = Field(description="What the transaction did.")


class Participant(BaseModel):
    """One address or contract involved in a transaction, and how."""

    address: str = Field(description="Address or contract id.")
    role: str = Field(
        description="What it did: `sender`, `recipient`, `contract`, `stacker`, `delegate`, "
        "`caller`, `deployer`, `sponsor`, `miner`, `input` or `output`."
    )


class TransactionExplanation(BaseModel):
    """One transaction decoded into plain English plus the specifics behind it."""

    txid: str = Field(description="Normalised transaction id, `0x`-prefixed on Stacks.")
    chain: Chain = Field(description="`btc` or `stx`.")
    kind: ExplainKind = Field(description="Which decode case matched, `unknown` for the fallback.")
    summary: str = Field(description="One plain-English sentence describing the transaction.")
    detail: dict[str, DetailValue] = Field(description="The decoded specifics behind the summary.")
    fee: str = Field(
        description="Fee as a human string: sat/vB on Bitcoin, STX and uSTX on Stacks."
    )
    status: TxStatus = Field(description="`confirmed`, `pending` or `failed`.")
    block_height: int | None = Field(description="Block height, or null while unconfirmed.")
    timestamp: str | None = Field(
        description="Block time as ISO 8601 UTC, or null while unconfirmed."
    )
    participants: list[Participant] = Field(
        description="Addresses and contracts involved, each with a role."
    )


class SummaryFailure(BaseModel):
    """One part of an address snapshot that could not be read, and why."""

    part: str = Field(
        description="Which read failed: `STX balance`, `token balances` or `recent transactions`."
    )
    reason: str = Field(description="What the upstream said.")


class RecentTransactions(BaseModel):
    """A page of recent transactions for one address."""

    address: str = Field(description="The address that was queried.")
    chain: Chain = Field(description="Chain the transactions were read from.")
    transactions: list[TransactionSummary] = Field(description="Newest first.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(
        cls, address: str, chain: Chain, transactions: list[TransactionSummary]
    ) -> RecentTransactions:
        short = short_address(address)
        unit = "BTC" if chain == "btc" else "STX"
        if not transactions:
            summary = f"{short} has no recent {unit} transactions"
            return cls(address=address, chain=chain, transactions=transactions, summary=summary)
        counts = {
            name: sum(1 for tx in transactions if tx.direction == name)
            for name in ("in", "out", "self", "other")
        }
        breakdown = ", ".join(f"{count} {name}" for name, count in counts.items() if count)
        pending = sum(1 for tx in transactions if tx.status == "pending")
        pending_note = "" if pending == 0 else f", {pending} still unconfirmed"
        latest = transactions[0].timestamp or "pending"
        summary = (
            f"{short} has {len(transactions)} recent {unit} transactions ({breakdown})"
            f"{pending_note}, most recent {latest}"
        )
        return cls(address=address, chain=chain, transactions=transactions, summary=summary)


FeePriority = Literal["no_priority", "low_priority", "medium_priority", "high_priority"]


class FeeOption(BaseModel):
    """One fee tier for a Stacks transfer, as an absolute amount."""

    priority: FeePriority = Field(description="Which tier, from `no_priority` to `high_priority`.")
    fee_ustx: int = Field(description="Absolute fee in micro-STX, not a rate per byte.")
    fee_stx: str = Field(description="The same fee in STX, 6 decimal places.")


class StxTransferDraft(BaseModel):
    """An unsigned STX transfer for a wallet to review, sign and broadcast itself.

    Nothing here is signed and no key was involved in producing it. The fields
    are the inputs a wallet needs to build the transaction: it supplies the
    public key, signs, and broadcasts. This server does none of those.
    """

    signed: bool = Field(
        description="Always false. This server holds no key, never signs and never broadcasts."
    )
    sender: str = Field(description="Standard principal that would send, SP... or SM...")
    recipient: str = Field(description="Principal that would receive; may be a contract.")
    amount_ustx: int = Field(description="Amount to send, in micro-STX.")
    amount_stx: str = Field(description="The same amount in STX, 6 decimal places.")
    memo: str | None = Field(description="Transfer memo, at most 34 bytes, or null.")
    nonce: int = Field(description="Sender's next usable nonce, read from the Hiro API.")
    network: str = Field(description="Always `mainnet`. This server reads mainnet only.")
    fees: list[FeeOption] = Field(
        description="Current fee tiers for a token transfer, cheapest first."
    )
    sender_balance_ustx: int = Field(description="Sender's total balance in micro-STX.")
    sender_balance_stx: str = Field(description="Sender's total balance in STX, 6 decimal places.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(
        cls,
        sender: str,
        recipient: str,
        amount_ustx: int,
        memo: str | None,
        nonce: int,
        fees: list[FeeOption],
        balance_ustx: int,
    ) -> StxTransferDraft:
        amount_stx = ustx_to_stx(amount_ustx)
        balance_stx = ustx_to_stx(balance_ustx)
        cheapest = min(fee.fee_ustx for fee in fees)
        affordable = balance_ustx >= amount_ustx + cheapest
        # The balance includes any stacked STX, so this says the balance covers
        # it, not that the transfer will land: a locked balance cannot be spent.
        cover = (
            f"balance of {balance_stx} STX covers it"
            if affordable
            else f"balance of {balance_stx} STX does not cover it"
        )
        summary = (
            f"Unsigned draft: {short_address(sender)} would send {amount_stx} STX to "
            f"{short_address(recipient)} at nonce {nonce}, fee {ustx_to_stx(cheapest)} STX "
            f"and up; the {cover}. Not signed and not broadcast"
        )
        return cls(
            signed=False,
            sender=sender,
            recipient=recipient,
            amount_ustx=amount_ustx,
            amount_stx=amount_stx,
            memo=memo,
            nonce=nonce,
            network="mainnet",
            fees=fees,
            sender_balance_ustx=balance_ustx,
            sender_balance_stx=balance_stx,
            summary=summary,
        )


def _continuation(summary: str, short: str) -> str:
    """Drop the leading short address, so three summaries read as one sentence."""
    prefix = f"{short} "
    return summary[len(prefix) :] if summary.startswith(prefix) else summary


class AddressSummary(BaseModel):
    """One snapshot of a Stacks principal: STX, tokens and recent transactions.

    Every part is optional. A part that could not be read is ``None`` and named
    in ``failures``, so one upstream failure costs that part and nothing else.
    """

    address: str = Field(description="The Stacks principal that was queried.")
    stx: StxBalance | None = Field(description="STX balance and lock state, null if unavailable.")
    tokens: TokenBalances | None = Field(
        description="SIP-10 positions including sBTC, null if unavailable."
    )
    transactions: RecentTransactions | None = Field(
        description="Most recent transactions, newest first, null if unavailable."
    )
    failures: list[SummaryFailure] = Field(description="Parts that could not be read, and why.")
    summary: str = Field(description="One-sentence human-readable summary.")

    @classmethod
    def build(
        cls,
        address: str,
        stx: StxBalance | None,
        tokens: TokenBalances | None,
        transactions: RecentTransactions | None,
        failures: list[SummaryFailure],
    ) -> AddressSummary:
        short = short_address(address)
        available = [part for part in (stx, tokens, transactions) if part is not None]
        missing = ", ".join(failure.part for failure in failures)
        if not available:
            summary = f"{short}: nothing could be read, {missing} all failed"
        else:
            body = "; ".join(_continuation(part.summary, short) for part in available)
            note = "" if not failures else f"; could not read {missing}"
            summary = f"{short} {body}{note}"
        return cls(
            address=address,
            stx=stx,
            tokens=tokens,
            transactions=transactions,
            failures=failures,
            summary=summary,
        )
