from stacks_mcp.models import (
    BtcBalance,
    RecentTransactions,
    StxBalance,
    TokenBalance,
    TokenBalances,
    TransactionSummary,
    base_units_to_amount,
    sats_to_btc,
    unix_to_iso,
    ustx_to_stx,
)


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


def test_ustx_to_stx_is_six_decimal_places() -> None:
    assert ustx_to_stx(0) == "0.000000"
    assert ustx_to_stx(1) == "0.000001"
    assert ustx_to_stx(1_000_000) == "1.000000"
    assert ustx_to_stx(1_965_379_994) == "1965.379994"


def test_base_units_to_amount_uses_declared_decimals() -> None:
    assert base_units_to_amount(129, 8) == "0.00000129"
    assert base_units_to_amount(10_000_000, 6) == "10.000000"
    assert base_units_to_amount(999_000_000, 0) == "999000000"


def test_unix_to_iso() -> None:
    assert unix_to_iso(None) is None
    assert unix_to_iso(1_785_585_728) == "2026-08-01T12:02:08Z"


def test_stx_balance_summary() -> None:
    balance = StxBalance.build(
        address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
        balance_ustx=1_965_379_994,
        locked_ustx=0,
        nonce=3833,
    )
    assert balance.balance_stx == "1965.379994"
    assert balance.locked_stx == "0.000000"
    assert balance.summary == ("SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833")


def test_stx_balance_summary_mentions_stacking() -> None:
    balance = StxBalance.build(
        address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
        balance_ustx=3_000_000_000,
        locked_ustx=2_000_000_000,
        nonce=1,
    )
    assert "2000.000000 STX locked by stacking" in balance.summary


def test_token_balances_summary_notes_unknown_metadata() -> None:
    tokens = [
        TokenBalance(
            contract_id="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token",
            symbol="sBTC",
            decimals=8,
            balance_raw="129",
            balance="0.00000129",
            is_sbtc=True,
        ),
        TokenBalance(
            contract_id="SP14XEKF7G8Q4WFYBSE77XSDMM67GTVF95R4V680.pixelstacks",
            symbol="pixelstacks",
            decimals=0,
            balance_raw="999000000",
            balance="999000000",
            is_sbtc=False,
        ),
    ]
    balances = TokenBalances.build(
        address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4", tokens=tokens, unknown=1
    )
    assert balances.summary == (
        "SM3VDX...JFQ4 holds 2 fungible tokens: 0.00000129 sBTC, 999000000 pixelstacks"
        "; metadata unknown for 1 of them, shown in base units"
    )


def test_empty_token_balances_summary() -> None:
    balances = TokenBalances.build(
        address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4", tokens=[], unknown=0
    )
    assert balances.summary == "SM3VDX...JFQ4 holds no fungible tokens"


def _summary(direction: str, status: str = "confirmed") -> TransactionSummary:
    return TransactionSummary(
        txid="0xab",
        chain="stx",
        timestamp="2026-08-01T12:02:08Z" if status == "confirmed" else None,
        direction=direction,  # type: ignore[arg-type]
        amount="1.000000",
        counterparty=None,
        status=status,  # type: ignore[arg-type]
        kind="token_transfer",
    )


def test_recent_transactions_summary_counts_directions() -> None:
    result = RecentTransactions.build(
        address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
        chain="stx",
        transactions=[_summary("in"), _summary("out"), _summary("out")],
    )
    assert result.summary == (
        "SM3VDX...JFQ4 has 3 recent STX transactions (1 in, 2 out), "
        "most recent 2026-08-01T12:02:08Z"
    )


def test_recent_transactions_summary_flags_pending() -> None:
    result = RecentTransactions.build(
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        chain="btc",
        transactions=[_summary("in", status="pending")],
    )
    assert "1 still unconfirmed" in result.summary
    assert "most recent pending" in result.summary


def test_empty_recent_transactions_summary() -> None:
    result = RecentTransactions.build(
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", chain="btc", transactions=[]
    )
    assert result.summary == "1A1zP1...vfNa has no recent BTC transactions"
