"""Decode one Bitcoin transaction into plain English.

Every function here is pure: it reads a ``MempoolTransaction`` and returns a
value. No HTTP, no clock, no model call, so the same bytes always produce the
same sentence. Detection lives in the small named predicates below and the first
match wins, so the order inside :func:`decode_btc_transaction` is the
specification. `DESIGN.md` holds the case table.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from stacks_mcp.clients.mempool import MempoolTransaction
from stacks_mcp.models import (
    DetailValue,
    ExplainKind,
    Participant,
    TransactionExplanation,
    sats_to_btc,
    short_address,
    unix_to_iso,
)

# Five is the point where a spend stops looking like a payment with change and
# starts looking like a sweep or a payout batch.
CONSOLIDATION_MIN_INPUTS = 5
BATCH_MIN_OUTPUTS = 5
# A consolidation can have fifty inputs. Name a few of each side and let
# `detail` carry the true counts.
MAX_PARTICIPANTS_PER_SIDE = 5
WEIGHT_UNITS_PER_VBYTE = 4


def input_addresses(tx: MempoolTransaction) -> list[str]:
    """Distinct addresses funding the transaction, in input order.

    Coinbase inputs have no previous output, so they contribute nothing.
    """
    seen: list[str] = []
    for vin in tx.vin:
        if vin.prevout is None:
            continue
        address = vin.prevout.scriptpubkey_address
        if address is not None and address not in seen:
            seen.append(address)
    return seen


def output_addresses(tx: MempoolTransaction) -> list[str]:
    """Distinct addresses paid by the transaction, in output order."""
    seen: list[str] = []
    for out in tx.vout:
        if out.scriptpubkey_address is not None and out.scriptpubkey_address not in seen:
            seen.append(out.scriptpubkey_address)
    return seen


def is_coinbase(tx: MempoolTransaction) -> bool:
    """True when a miner created this transaction to claim a block reward."""
    return any(vin.is_coinbase for vin in tx.vin)


def is_consolidation(tx: MempoolTransaction) -> bool:
    """True when many inputs are swept into a single output."""
    return len(tx.vin) >= CONSOLIDATION_MIN_INPUTS and len(tx.vout) == 1


def is_batch_payment(tx: MempoolTransaction) -> bool:
    """True when one input is split across many outputs."""
    return len(tx.vin) == 1 and len(tx.vout) >= BATCH_MIN_OUTPUTS


def is_self_send(tx: MempoolTransaction) -> bool:
    """True when every output pays an address that also funded the transaction."""
    ins, outs = input_addresses(tx), output_addresses(tx)
    return bool(ins) and bool(outs) and set(outs) <= set(ins)


def has_op_return(tx: MempoolTransaction) -> bool:
    """True when the transaction carries data in an unspendable output."""
    return any(out.is_op_return for out in tx.vout)


def vsize(tx: MempoolTransaction) -> int:
    """Virtual size in vbytes, rounded up, as fee rates are quoted against it.

    mempool.space returns weight rather than vsize, and one vbyte is four weight
    units.
    """
    if tx.weight <= 0:
        return 0
    return -(-tx.weight // WEIGHT_UNITS_PER_VBYTE)


def fee_rate(tx: MempoolTransaction) -> str:
    """Fee per vbyte to two decimal places, as a string to avoid float drift."""
    size = vsize(tx)
    if size <= 0:
        return "0.00"
    rate = Decimal(tx.fee) / Decimal(size)
    return str(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def format_fee(tx: MempoolTransaction) -> str:
    """The fee as a human string, absolute and per vbyte."""
    return f"{tx.fee:,} sats ({fee_rate(tx)} sat/vB)"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural or singular + 's'}"


def _output_total(tx: MempoolTransaction) -> int:
    return sum(out.value for out in tx.vout)


def _input_total(tx: MempoolTransaction) -> int:
    return sum(vin.prevout.value for vin in tx.vin if vin.prevout is not None)


def _paid_outputs(tx: MempoolTransaction) -> tuple[int, list[str]]:
    """Value and addresses of outputs that are neither change nor data.

    An output paying an address that also funded the transaction is treated as
    change, which is the usual shape of a payment with a remainder.
    """
    funding = set(input_addresses(tx))
    total = 0
    addresses: list[str] = []
    for out in tx.vout:
        address = out.scriptpubkey_address
        if out.is_op_return or address is None or address in funding:
            continue
        total += out.value
        if address not in addresses:
            addresses.append(address)
    return total, addresses


def _destination(addresses: list[str]) -> str:
    if not addresses:
        return "no addressed output"
    if len(addresses) == 1:
        return short_address(addresses[0])
    return f"{len(addresses)} addresses"


def _where(tx: MempoolTransaction) -> str:
    height = tx.status.block_height
    return f"in block {height}" if height is not None else "while still unconfirmed"


def _participants(tx: MempoolTransaction) -> list[Participant]:
    inputs = input_addresses(tx)[:MAX_PARTICIPANTS_PER_SIDE]
    outputs = output_addresses(tx)[:MAX_PARTICIPANTS_PER_SIDE]
    return [Participant(address=address, role="input") for address in inputs] + [
        Participant(address=address, role="output") for address in outputs
    ]


def _detail(tx: MempoolTransaction) -> dict[str, DetailValue]:
    paid_sats, paid_addresses = _paid_outputs(tx)
    output_total = _output_total(tx)
    return {
        "input_count": len(tx.vin),
        "output_count": len(tx.vout),
        "input_addresses": len(input_addresses(tx)),
        "output_addresses": len(output_addresses(tx)),
        "input_total_sats": _input_total(tx),
        "output_total_sats": output_total,
        "output_total_btc": sats_to_btc(output_total),
        "paid_sats": paid_sats,
        "paid_btc": sats_to_btc(paid_sats),
        "paid_addresses": paid_addresses[:MAX_PARTICIPANTS_PER_SIDE],
        "change_sats": output_total - paid_sats,
        "fee_sats": tx.fee,
        "fee_sat_vb": fee_rate(tx),
        "weight": tx.weight,
        "vsize": vsize(tx),
        "op_return": has_op_return(tx),
    }


def _core_sentence(tx: MempoolTransaction) -> tuple[ExplainKind, str]:
    """Pick the case and build the sentence without its final punctuation."""
    fee = format_fee(tx)
    output_total = _output_total(tx)
    if is_coinbase(tx):
        return "coinbase", (
            f"Coinbase: {sats_to_btc(output_total)} BTC of block reward and fees paid to "
            f"{_plural(len(tx.vout), 'output')} {_where(tx)}"
        )
    if is_consolidation(tx):
        destination = _destination(output_addresses(tx))
        return "consolidation", (
            f"Consolidation: {_plural(len(tx.vin), 'input')} from "
            f"{_plural(len(input_addresses(tx)), 'address', 'addresses')} swept into "
            f"{sats_to_btc(output_total)} BTC at {destination}, fee {fee}"
        )
    if is_batch_payment(tx):
        return "batch_payment", (
            f"Batch payment: {_plural(len(tx.vin), 'input')} split across "
            f"{_plural(len(tx.vout), 'output')} to "
            f"{_plural(len(output_addresses(tx)), 'address', 'addresses')} totalling "
            f"{sats_to_btc(output_total)} BTC, fee {fee}"
        )
    if is_self_send(tx):
        moved_between = _plural(len(output_addresses(tx)), "address", "addresses")
        return "self_send", (
            f"Self-send: {sats_to_btc(output_total)} BTC moved between {moved_between} "
            f"the sender already controls, {_plural(len(tx.vin), 'input')}, "
            f"{_plural(len(tx.vout), 'output')}, fee {fee}"
        )
    paid_sats, paid_addresses = _paid_outputs(tx)
    return "btc_transfer", (
        f"BTC transfer of {sats_to_btc(paid_sats)} BTC to {_destination(paid_addresses)}, "
        f"{_plural(len(tx.vin), 'input')}, {_plural(len(tx.vout), 'output')}, fee {fee}"
    )


def decode_btc_transaction(tx: MempoolTransaction) -> TransactionExplanation:
    """Decode one Bitcoin transaction. Total: never raises, always explains.

    An OP_RETURN output is a modifier rather than a case of its own, so it is
    appended to whichever sentence matched. Coinbase is exempt, because every
    coinbase carries a witness-commitment OP_RETURN and saying so would tell the
    reader nothing.
    """
    kind, sentence = _core_sentence(tx)
    if has_op_return(tx) and kind != "coinbase":
        sentence = f"{sentence}, plus an OP_RETURN output"
    return TransactionExplanation(
        txid=tx.txid,
        chain="btc",
        kind=kind,
        summary=f"{sentence}.",
        detail=_detail(tx),
        fee=format_fee(tx),
        status="confirmed" if tx.status.confirmed else "pending",
        block_height=tx.status.block_height,
        timestamp=unix_to_iso(tx.status.block_time),
        participants=_participants(tx),
    )
