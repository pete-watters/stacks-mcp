"""Normalise Bitcoin and Stacks transactions into one shape.

Direction always describes value flow as seen by the queried address:

- ``in``: the address only received value.
- ``out``: the address only sent value.
- ``self``: it was on both sides, for example a Bitcoin change output.
- ``other``: no value moved. A Stacks contract call that only pays a fee is
  reported as ``out`` because the address initiated it.
"""

from __future__ import annotations

from stacks_mcp.clients.hiro import HiroPrincipalTransaction
from stacks_mcp.clients.mempool import MempoolTransaction
from stacks_mcp.models import (
    Direction,
    TransactionSummary,
    TxKind,
    sats_to_btc,
    unix_to_iso,
    ustx_to_stx,
)

_STX_KINDS: dict[str, TxKind] = {
    "token_transfer": "token_transfer",
    "contract_call": "contract_call",
    "smart_contract": "smart_contract",
    "coinbase": "coinbase",
}


def _other_party(candidate: str | None, address: str) -> str | None:
    return candidate if candidate is not None and candidate != address else None


def btc_transaction_summary(tx: MempoolTransaction, address: str) -> TransactionSummary:
    """Normalise one mempool.space transaction against the queried address."""
    sent = tx.value_sent_by(address)
    received = tx.value_received_by(address)
    direction: Direction
    if sent > 0 and received > 0:
        direction, amount_sats = "self", abs(sent - received)
    elif sent > 0:
        direction, amount_sats = "out", sent
    elif received > 0:
        direction, amount_sats = "in", received
    else:
        direction, amount_sats = "other", 0
    return TransactionSummary(
        txid=tx.txid,
        chain="btc",
        timestamp=unix_to_iso(tx.status.block_time),
        direction=direction,
        amount=sats_to_btc(amount_sats),
        counterparty=tx.counterparty_for(address),
        status="confirmed" if tx.status.confirmed else "pending",
        kind="coinbase" if tx.is_coinbase else "transfer",
    )


def _stx_counterparty(item: HiroPrincipalTransaction, principal: str) -> str | None:
    tx = item.transaction
    if tx.contract_call is not None:
        return _other_party(tx.contract_call.contract_id, principal)
    if tx.smart_contract is not None:
        return _other_party(tx.smart_contract.contract_id, principal)
    if tx.token_transfer is not None and tx.sender.address == principal:
        return _other_party(tx.token_transfer.recipient, principal)
    if tx.coinbase is not None:
        return _other_party(tx.coinbase.alt_recipient, principal)
    return _other_party(tx.sender.address, principal)


def stx_transaction_summary(item: HiroPrincipalTransaction, principal: str) -> TransactionSummary:
    """Normalise one Hiro principal transaction against the queried principal.

    ``balance_changes.stx.sent`` includes the transaction fee, so the fee is
    subtracted when the principal sent the transaction. What is left is the STX
    actually transferred, which is ``0`` for a plain contract call.
    """
    tx = item.transaction
    change = item.balance_changes.stx
    fee = int(tx.fee_rate) if item.involvement == "sender" else 0
    sent = max(int(change.sent) - fee, 0)
    received = int(change.received)
    direction: Direction
    if sent > 0 and received > 0:
        direction, amount_ustx = "self", sent
    elif sent > 0:
        direction, amount_ustx = "out", sent
    elif received > 0:
        direction, amount_ustx = "in", received
    elif item.involvement == "sender":
        direction, amount_ustx = "out", 0
    else:
        direction, amount_ustx = "other", 0
    return TransactionSummary(
        txid=tx.tx_id,
        chain="stx",
        timestamp=unix_to_iso(tx.block.time),
        direction=direction,
        amount=ustx_to_stx(amount_ustx),
        counterparty=_stx_counterparty(item, principal),
        status="confirmed" if tx.status == "success" else "failed",
        kind=_STX_KINDS.get(tx.type, "other"),
    )
