"""Direction, amount and counterparty detection, against recorded and synthetic inputs."""

from typing import Any

from stacks_mcp.clients.hiro import HiroPrincipalTransaction
from stacks_mcp.clients.mempool import MempoolTransaction
from stacks_mcp.transactions import btc_transaction_summary, stx_transaction_summary

from .conftest import GENESIS, SBTC_DEPLOYER

OTHER_BTC = "bc1qdrkwnsd08fxcz6hqaxfnq86eg8njxmjrc6wpyq"
OTHER_STX = "SP2ADT4TAV92SPBNP3WE9GPJ12F6CKGWMEJ1H1BB9"


def _btc_tx(
    vin: list[dict[str, Any]], vout: list[dict[str, Any]], confirmed: bool = True
) -> MempoolTransaction:
    """Build a minimal transaction. Recorded fixtures cover the real shapes;
    this covers the flows the genesis address never performs, such as spending."""
    status: dict[str, Any] = {"confirmed": confirmed}
    if confirmed:
        status |= {"block_height": 900_000, "block_time": 1_700_000_000}
    return MempoolTransaction.model_validate(
        {"txid": "0x" + "ab" * 32, "fee": 500, "status": status, "vin": vin, "vout": vout}
    )


def _vin(address: str | None, value: int, is_coinbase: bool = False) -> dict[str, Any]:
    if is_coinbase:
        return {"is_coinbase": True, "prevout": None}
    return {
        "is_coinbase": False,
        "prevout": {"scriptpubkey_address": address, "value": value},
    }


def _vout(address: str | None, value: int) -> dict[str, Any]:
    return {"scriptpubkey_address": address, "value": value}


def test_btc_incoming_from_fixture(genesis_txs_fixture: list[dict[str, Any]]) -> None:
    tx = MempoolTransaction.model_validate(genesis_txs_fixture[2])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.direction == "in"
    assert summary.amount == "0.00000546"
    assert summary.counterparty == OTHER_BTC
    assert summary.status == "confirmed"
    assert summary.timestamp == "2026-09-16T15:11:18Z"
    assert summary.kind == "transfer"


def test_btc_unconfirmed_has_no_timestamp(genesis_txs_fixture: list[dict[str, Any]]) -> None:
    tx = MempoolTransaction.model_validate(genesis_txs_fixture[0])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.status == "pending"
    assert summary.timestamp is None
    assert summary.direction == "in"


def test_btc_outgoing() -> None:
    tx = _btc_tx([_vin(GENESIS, 100_000)], [_vout(OTHER_BTC, 99_500)])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.direction == "out"
    assert summary.amount == "0.00100000"
    assert summary.counterparty == OTHER_BTC


def test_btc_self_send_reports_net_movement() -> None:
    tx = _btc_tx([_vin(GENESIS, 100_000)], [_vout(OTHER_BTC, 40_000), _vout(GENESIS, 59_500)])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.direction == "self"
    assert summary.amount == "0.00040500"
    assert summary.counterparty == OTHER_BTC


def test_btc_unrelated_transaction_is_other() -> None:
    tx = _btc_tx([_vin(OTHER_BTC, 10_000)], [_vout(OTHER_BTC, 9_500)])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.direction == "other"
    assert summary.amount == "0.00000000"


def test_btc_coinbase() -> None:
    tx = _btc_tx([_vin(None, 0, is_coinbase=True)], [_vout(GENESIS, 5_000_000_000)])
    summary = btc_transaction_summary(tx, GENESIS)
    assert summary.kind == "coinbase"
    assert summary.direction == "in"
    assert summary.amount == "50.00000000"
    assert summary.counterparty is None


def test_stx_incoming_token_transfer_from_fixture(
    stx_transactions_fixture: dict[str, Any],
) -> None:
    item = HiroPrincipalTransaction.model_validate(stx_transactions_fixture["results"][0])
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.direction == "in"
    assert summary.amount == "385.513100"
    assert summary.counterparty == OTHER_STX
    assert summary.kind == "token_transfer"
    assert summary.status == "confirmed"
    assert summary.timestamp == "2026-08-01T12:02:08Z"


def test_stx_contract_call_pays_only_a_fee(stx_transactions_fixture: dict[str, Any]) -> None:
    item = HiroPrincipalTransaction.model_validate(stx_transactions_fixture["results"][1])
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.direction == "out"
    assert summary.amount == "0.000000"
    assert summary.kind == "contract_call"
    assert summary.counterparty == f"{SBTC_DEPLOYER}.sbtc-bootstrap-signers"


def _stx_transfer_item(
    sender: str, recipient: str, amount: str, sent: str, received: str, involvement: str
) -> HiroPrincipalTransaction:
    return HiroPrincipalTransaction.model_validate(
        {
            "transaction": {
                "tx_id": "0x" + "cd" * 32,
                "sender": {"address": sender, "nonce": 1},
                "sponsor": None,
                "fee_rate": "1000",
                "block": {
                    "height": 100,
                    "hash": "0x00",
                    "index_hash": "0x00",
                    "time": 1_700_000_000,
                    "tx_index": 0,
                },
                "bitcoin_block": {"height": 90, "time": 1_700_000_000},
                "status": "success",
                "type": "token_transfer",
                "token_transfer": {"recipient": recipient, "amount": amount, "memo": None},
            },
            "involvement": involvement,
            "balance_changes": {
                "stx": {"sent": sent, "received": received, "net": "0"},
            },
            "affected_balances": {"stx": True, "ft": False, "nft": False},
        }
    )


def test_stx_outgoing_transfer_excludes_the_fee() -> None:
    item = _stx_transfer_item(
        SBTC_DEPLOYER, OTHER_STX, "5000000", sent="5001000", received="0", involvement="sender"
    )
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.direction == "out"
    assert summary.amount == "5.000000"
    assert summary.counterparty == OTHER_STX


def test_stx_self_transfer() -> None:
    item = _stx_transfer_item(
        SBTC_DEPLOYER,
        SBTC_DEPLOYER,
        "2000000",
        sent="2001000",
        received="2000000",
        involvement="sender",
    )
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.direction == "self"
    assert summary.amount == "2.000000"
    assert summary.counterparty is None


def test_stx_failed_transaction() -> None:
    item = _stx_transfer_item(
        SBTC_DEPLOYER, OTHER_STX, "1000000", sent="1000", received="0", involvement="sender"
    )
    item.transaction.status = "abort_by_post_condition"
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.status == "failed"


def test_stx_unknown_type_is_other() -> None:
    item = _stx_transfer_item(
        OTHER_STX, OTHER_STX, "1000000", sent="0", received="0", involvement="affected"
    )
    item.transaction.type = "tenure_change"
    item.transaction.token_transfer = None
    summary = stx_transaction_summary(item, SBTC_DEPLOYER)
    assert summary.kind == "other"
    assert summary.direction == "other"
    assert summary.amount == "0.000000"
    assert summary.counterparty == OTHER_STX
