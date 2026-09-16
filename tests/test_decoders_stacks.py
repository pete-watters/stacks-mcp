"""One test per Stacks decode case, asserting the exact sentence.

Every fixture is a verbatim recording of one mainnet transaction; the txid of
each is in the docstring of its test so a reviewer can check it on an explorer.
The decoders are pure, so these tests build models from fixtures and call them
directly, with no HTTP at all.
"""

from __future__ import annotations

from typing import Any

from stacks_mcp.clients.hiro import (
    HiroTransactionDetail,
    HiroTransactionEvent,
    HiroTransactionEvents,
)
from stacks_mcp.decoders.stacks import decode_stacks_transaction

from .conftest import load_fixture


def _tx(name: str) -> HiroTransactionDetail:
    return HiroTransactionDetail.model_validate(load_fixture("hiro", name))


def _events(name: str) -> list[HiroTransactionEvent]:
    return HiroTransactionEvents.model_validate(load_fixture("hiro", name)).results


def test_stx_transfer() -> None:
    """0xc2f1cefb6e463507fcdd00d8cf9f13a3c2166bdf3471735b62d45542152009f8."""
    result = decode_stacks_transaction(_tx("v3_tx_stx_transfer.json"), [])
    assert result.kind == "stx_transfer"
    assert result.summary == ("STX transfer of 385.513100 STX from SP2ADT...1BB9 to SM3VDX...JFQ4.")
    assert result.chain == "stx"
    assert result.status == "confirmed"
    assert result.fee == "0.300000 STX (300,000 uSTX)"
    assert result.block_height == 8681937
    assert result.timestamp == "2026-08-01T12:02:08Z"
    assert result.detail["amount_ustx"] == 385_513_100
    assert [p.role for p in result.participants] == ["sender", "recipient"]


def test_sbtc_withdrawal_wins_over_deposit() -> None:
    """0x4e8b2f6c148f6709241fce71f87fc6e6ebd994ac447d4b1e86526213a4caa212.

    This transaction both burns `sbtc-token` and mints `sbtc-token-locked`, so it
    would also satisfy the deposit rule. Withdrawal is checked first, and that
    ordering is what this asserts.
    """
    events = _events("v3_tx_events_sbtc_withdrawal.json")
    assert {event.ft_asset.type for event in events if event.ft_asset} == {"burn", "mint"}
    result = decode_stacks_transaction(_tx("v3_tx_sbtc_withdrawal.json"), events)
    assert result.kind == "sbtc_withdrawal"
    assert result.summary == (
        "sBTC withdrawal of 0.15000720 sBTC burned from SP3A7M...M51D "
        "via sbtc-withdrawal::initiate-withdrawal-request."
    )
    assert result.detail["amount_sbtc"] == "0.15000720"


def test_sbtc_deposit() -> None:
    """0xd044e48842e5ba34e1d05bebd8e0a9519192624d61114848460dcba4c9611db6."""
    result = decode_stacks_transaction(
        _tx("v3_tx_sbtc_deposit.json"), _events("v3_tx_events_sbtc_deposit.json")
    )
    assert result.kind == "sbtc_deposit"
    assert result.summary == (
        "sBTC deposit of 0.00098076 sBTC minted to SP2WS9...JF7A "
        "via sbtc-deposit::complete-deposit-wrapper."
    )
    assert result.detail["recipient"] == "SP2WS9QFNR8VMJZY6VWWFZNPKN7ZTVP746BMXJF7A"


def test_sip10_transfer_of_sbtc() -> None:
    """0xc39e71f37795f4a1a5a80c304bfb0beb15b582ca12480afd2cd7b0e9244e9343."""
    result = decode_stacks_transaction(
        _tx("v3_tx_sbtc_transfer.json"), _events("v3_tx_events_sbtc_transfer.json")
    )
    assert result.kind == "sip10_transfer"
    assert result.summary == (
        "SIP-10 transfer of 0.00000100 sBTC from SP20GP...QJE1 to SP2GHQ...SF3B "
        "via sbtc-token::transfer."
    )
    assert result.detail["is_sbtc"] is True
    assert [p.role for p in result.participants] == ["sender", "recipient", "contract"]


def test_stacking_stack_stx() -> None:
    """0x995fb653065c74596b63e6cc9c10fb8fa7b8f3574d5ea089b45d3e11d9e7336e."""
    result = decode_stacks_transaction(
        _tx("v3_tx_pox4_stack_stx.json"), _events("v3_tx_events_pox4_stack_stx.json")
    )
    assert result.kind == "stacking"
    assert result.summary == (
        "Stacking: SP14S2...KHCB locked 4491100.000000 STX for 1 cycle via pox-4::stack-stx."
    )
    assert result.detail["lock_period_cycles"] == 1
    # `amount-ustx` comes from the call argument, the lock total from the event.
    assert result.detail["amount_ustx"] == 4_491_100_000_000
    assert result.detail["total_locked_ustx"] == 4_491_100_000_000
    assert result.detail["unlock_bitcoin_height"] == 962_150


def test_stacking_delegate_stx_names_the_delegate() -> None:
    """0x347b4eeba41fb3fed551cb1a90f7da43dd861246b8db625dc88708e6266017be."""
    result = decode_stacks_transaction(
        _tx("v3_tx_pox4_delegate_stx.json"), _events("v3_tx_events_pox4_delegate_stx.json")
    )
    assert result.kind == "stacking"
    assert result.summary == (
        "Stacking: SP2Z2C...J7J9 delegated up to 3937.196763 STX to SP1JAG...JV91 "
        "via pox-4::delegate-stx."
    )
    assert result.detail["delegate_to"] == "SP1JAG6TV2XRYFGJN7CAAN6Z3CEW2YMZWMHJAJV91"
    assert [p.role for p in result.participants] == ["stacker", "contract", "delegate"]


def test_stacking_stack_increase() -> None:
    """0x7b13f1d6dc5ae12f1c949ee60c312381588e822baf275ad6f092a03b2d4deacd."""
    result = decode_stacks_transaction(
        _tx("v3_tx_pox4_stack_increase.json"), _events("v3_tx_events_pox4_stack_increase.json")
    )
    assert result.kind == "stacking"
    assert result.summary == (
        "Stacking: SP1JR9...PA4D added 15184.000000 STX to an existing lock "
        "via pox-4::stack-increase."
    )
    # The event reports the resulting lock, which is larger than the increase.
    assert result.detail["amount_ustx"] == 15_184_000_000
    assert result.detail["total_locked_ustx"] == 293_519_000_000


def test_contract_call_truncates_long_arguments() -> None:
    """0x577a7cfac2e54b0f5c29832730234a28dcfcce0b610c393baba5e3971c4c60c9."""
    result = decode_stacks_transaction(
        _tx("v3_tx_contract_call.json"), _events("v3_tx_events_contract_call.json")
    )
    assert result.kind == "contract_call"
    assert result.summary == (
        "Contract call sbtc-bootstrap-signers::rotate-keys-wrapper by SM3VDX...JFQ4 "
        "with 3 arguments: (list 0x024020d254667b90..., "
        "0x0204cff1ade0cc7f74d1b5..., u10."
    )
    assert result.detail["argument_count"] == 3


def test_contract_deploy() -> None:
    """0xbf406ea1fbd35aa21917cbb144080bdb7e06b2e45ddd162b2ad9e4b4e522577d."""
    result = decode_stacks_transaction(_tx("v3_tx_contract_deploy.json"), [])
    assert result.kind == "contract_deploy"
    assert result.summary == "Contract deploy of zip-064 by SP2VCQ...QF4N, Clarity version 4."
    assert result.detail["clarity_version"] == 4


def test_coinbase() -> None:
    """0xe0c21e443323f3c72d18fe0e75f799a5de2a0775f622319d4daf86ada7cd9814."""
    result = decode_stacks_transaction(_tx("v3_tx_coinbase.json"), [])
    assert result.kind == "coinbase"
    assert result.summary == "Coinbase: block reward for Stacks block 9004429."


def test_tenure_change() -> None:
    """0xfa8a2b0546237badcf63e870f563bea3e80bb8a0961e2c350efaa513cfafbfda."""
    result = decode_stacks_transaction(_tx("v3_tx_tenure_change.json"), [])
    assert result.kind == "tenure_change"
    assert result.summary == "Tenure change at Stacks block 9004613, cause extended_read_count."


def test_reverted_transaction_keeps_its_case_and_gains_a_prefix() -> None:
    """0x4b6f46088f9fc759dfe23493ffb5fce82d69bd795a8a5069be7183ae3f886090.

    A transaction that aborted still says what it tried to do, so `kind` stays
    `contract_call` and only the sentence and `status` mark the failure.
    """
    result = decode_stacks_transaction(_tx("v3_tx_failed_contract_call.json"), [])
    assert result.kind == "contract_call"
    assert result.status == "failed"
    assert result.summary == (
        "Failed: Contract call multi-entry-v20::b21 by SP3DTE...5K3S "
        "with 2 arguments: (list), u2893."
    )


def _minimal_tx(**overrides: Any) -> HiroTransactionDetail:
    """A transaction with only the fields every Stacks transaction has."""
    body: dict[str, Any] = {
        "tx_id": "0x" + "ab" * 32,
        "sender": {"address": "SP2GHQRCRMYY4S8PMBR49BEKX144VR437YT42SF3B", "nonce": 7},
        "fee_rate": "180",
        "status": "success",
        "type": "poison_microblock",
        "event_count": 0,
        "block": {"height": 9004255, "time": 1758039855},
    }
    body.update(overrides)
    return HiroTransactionDetail.model_validate(body)


def test_unrecognised_type_falls_back_instead_of_raising() -> None:
    """Built by hand, not recorded.

    `poison_microblock` is the only Stacks transaction type this decoder does not
    name, and microblocks were retired at the Nakamoto hard fork, so mainnet has
    no recent example to record. The fields the fallback uses -- sender, fee,
    type and block -- are the ones every transaction carries, so a hand-built
    model exercises the same path a real one would.
    """
    result = decode_stacks_transaction(_minimal_tx(), [])
    assert result.kind == "unknown"
    assert result.summary == (
        "Stacks poison_microblock transaction by SP2GHQ...SF3B, "
        "fee 0.000180 STX (180 uSTX), confirmed in block 9004255."
    )
    assert result.detail["upstream_type"] == "poison_microblock"


def test_fallback_on_an_unconfirmed_transaction() -> None:
    """Built by hand: a pending transaction has no block, so there is no height."""
    result = decode_stacks_transaction(_minimal_tx(status="pending", block=None), [])
    assert result.kind == "unknown"
    assert result.status == "pending"
    assert result.block_height is None
    assert result.timestamp is None
    assert result.summary.endswith("still unconfirmed.")


def test_decoding_is_deterministic() -> None:
    """The same bytes give the same sentence, which is the point of no model."""
    tx, events = _tx("v3_tx_pox4_stack_stx.json"), _events("v3_tx_events_pox4_stack_stx.json")
    assert decode_stacks_transaction(tx, events) == decode_stacks_transaction(tx, events)
