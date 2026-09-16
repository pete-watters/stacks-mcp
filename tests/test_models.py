from stacks_mcp.models import BtcBalance, sats_to_btc


def test_sats_to_btc_is_eight_decimal_places() -> None:
    assert sats_to_btc(0) == "0.00000000"
    assert sats_to_btc(1) == "0.00000001"
    assert sats_to_btc(100_000_000) == "1.00000000"
    assert sats_to_btc(5747023635) == "57.47023635"


def test_build_summary() -> None:
    balance = BtcBalance.build(
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        confirmed_sats=5747023635,
        unconfirmed_sats=4218,
        tx_count=65805,
    )
    assert balance.confirmed_btc == "57.47023635"
    assert balance.summary == (
        "1A1zP1...vfNa holds 57.47023635 BTC across 65,805 transactions, 4,218 sats unconfirmed"
    )
