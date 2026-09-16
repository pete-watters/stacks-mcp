"""Pydantic output models returned by tools. Every model carries a ``summary``."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

SATS_PER_BTC = Decimal(100_000_000)


def sats_to_btc(sats: int) -> str:
    """Format satoshis as a BTC string with exactly 8 decimal places."""
    return f"{Decimal(sats) / SATS_PER_BTC:.8f}"


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
