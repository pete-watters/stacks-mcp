"""One test per Bitcoin decode case, asserting the exact sentence.

Every fixture is a verbatim recording of one mainnet transaction; the txid of
each is in the docstring of its test so a reviewer can check it on an explorer.
The decoders are pure, so these tests build models from fixtures and call them
directly, with no HTTP at all.
"""

from __future__ import annotations

from typing import Any

from stacks_mcp.clients.mempool import MempoolTransaction
from stacks_mcp.decoders.btc import decode_btc_transaction, fee_rate, vsize

from .conftest import load_fixture


def _tx(name: str) -> MempoolTransaction:
    return MempoolTransaction.model_validate(load_fixture("mempool", name))


def test_simple_transfer() -> None:
    """ec786e157e41a498dde976c5e4e324cb7bb6557832ebc0f3d67f0ffd7d5812fb."""
    result = decode_btc_transaction(_tx("tx_simple_transfer.json"))
    assert result.kind == "btc_transfer"
    assert result.summary == (
        "BTC transfer of 0.01310200 BTC to 2 addresses, 1 input, 2 outputs, "
        "fee 45,900 sats (300.00 sat/vB)."
    )
    assert result.chain == "btc"
    assert result.status == "confirmed"
    assert result.block_height == 967296
    assert result.timestamp == "2026-09-16T15:57:40Z"


def test_consolidation() -> None:
    """ace7cd6cd5d14b1f52a30ea81b576d0901737eb31ff50b98fa0fd48e3705d7e1."""
    result = decode_btc_transaction(_tx("tx_consolidation.json"))
    assert result.kind == "consolidation"
    assert result.summary == (
        "Consolidation: 51 inputs from 10 addresses swept into 1.37207743 BTC "
        "at bc1q6d...9l55, fee 24,829 sats (7.09 sat/vB)."
    )
    assert result.detail["input_count"] == 51
    assert result.detail["output_count"] == 1
    # Five per side keeps `participants` readable when there are 51 inputs.
    assert len(result.participants) == 6


def test_batch_payment() -> None:
    """0f6729f9d669a3adf19b2d35456e4b1fba16b1b8cc9d6679c6a7553cf4cb2b8b."""
    result = decode_btc_transaction(_tx("tx_batch_payment.json"))
    assert result.kind == "batch_payment"
    assert result.summary == (
        "Batch payment: 1 input split across 77 outputs to 72 addresses "
        "totalling 1.55202003 BTC, fee 270,500 sats (100.04 sat/vB)."
    )
    # 77 outputs across 72 addresses: five of them are paid twice.
    assert result.detail["output_count"] == 77
    assert result.detail["output_addresses"] == 72


def test_self_send() -> None:
    """a0fdce4c3d2c8e99c2744dcee8f1b438c72777ce87bcc6a84c7244ddc26fc52c."""
    result = decode_btc_transaction(_tx("tx_self_send.json"))
    assert result.kind == "self_send"
    assert result.summary == (
        "Self-send: 0.05603261 BTC moved between 2 addresses the sender already controls, "
        "3 inputs, 2 outputs, fee 55,381 sats (205.11 sat/vB)."
    )
    # Nothing left the wallet, so every output counts as change.
    assert result.detail["paid_sats"] == 0
    assert result.detail["change_sats"] == 5_603_261


def test_coinbase() -> None:
    """7d4e3dc2cfbef2aa033783c1c9ca1256670ed58073a2dd48987690c38e64d17a."""
    result = decode_btc_transaction(_tx("tx_coinbase.json"))
    assert result.kind == "coinbase"
    assert result.summary == (
        "Coinbase: 3.19050441 BTC of block reward and fees paid to 6 outputs in block 967296."
    )


def test_coinbase_does_not_mention_its_witness_commitment() -> None:
    """The same coinbase: every one carries an OP_RETURN, so saying so is noise."""
    tx = _tx("tx_coinbase.json")
    result = decode_btc_transaction(tx)
    assert result.detail["op_return"] is True
    assert "OP_RETURN" not in result.summary


def test_op_return_is_appended_to_the_matched_case() -> None:
    """1a80bf333087e468cd669ad1b08c1f6831a863bba2e4d4516149523461e0068c."""
    result = decode_btc_transaction(_tx("tx_op_return.json"))
    assert result.kind == "btc_transfer"
    assert result.summary == (
        "BTC transfer of 0.08388842 BTC to 2 addresses, 1 input, 3 outputs, "
        "fee 9,000 sats (54.88 sat/vB), plus an OP_RETURN output."
    )
    assert result.detail["op_return"] is True


def test_fee_rate_is_computed_from_weight() -> None:
    """mempool.space returns weight, not vsize, and 1 vbyte is 4 weight units."""
    tx = _tx("tx_consolidation.json")
    assert tx.weight == 14015
    # 14015 / 4 rounds up to 3504, and 24829 / 3504 is 7.09.
    assert vsize(tx) == 3504
    assert fee_rate(tx) == "7.09"


def _minimal_tx(**overrides: Any) -> MempoolTransaction:
    """A transaction with only the fields mempool.space always returns."""
    body: dict[str, Any] = {
        "txid": "ab" * 32,
        "fee": 0,
        "weight": 0,
        "status": {"confirmed": False},
        "vin": [],
        "vout": [],
    }
    body.update(overrides)
    return MempoolTransaction.model_validate(body)


def test_a_transaction_with_no_addressed_output_still_explains() -> None:
    """Built by hand: decoding is total, so an empty shape must not raise."""
    result = decode_btc_transaction(_minimal_tx())
    assert result.kind == "btc_transfer"
    assert result.summary == (
        "BTC transfer of 0.00000000 BTC to no addressed output, 0 inputs, 0 outputs, "
        "fee 0 sats (0.00 sat/vB)."
    )
    assert result.status == "pending"
    assert result.block_height is None
    assert result.timestamp is None


def test_decoding_is_deterministic() -> None:
    """The same bytes give the same sentence, which is the point of no model."""
    tx = _tx("tx_batch_payment.json")
    assert decode_btc_transaction(tx) == decode_btc_transaction(tx)
