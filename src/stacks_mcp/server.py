"""MCP application and tool registration."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from stacks_mcp import __version__
from stacks_mcp.clients.mempool import get_client
from stacks_mcp.errors import InvalidAddressError, UpstreamError
from stacks_mcp.models import BtcBalance
from stacks_mcp.validation import validate_btc_address

mcp = MCPServer(
    "stacks-mcp",
    instructions=(
        "Read-only Bitcoin and Stacks chain data. Tools never hold keys, sign or broadcast."
    ),
    version=__version__,
)


@mcp.tool()
async def get_btc_balance(address: str) -> BtcBalance:
    """Get the current balance of a Bitcoin mainnet address.

    Call this when the user asks how much BTC an address holds, whether an
    address has any unconfirmed activity, or how many transactions it has
    seen. Accepts legacy (1...), P2SH (3...) and bech32 (bc1...) addresses.

    Returns confirmed and unconfirmed balances in satoshis, the confirmed
    balance in BTC (8 decimal places), the confirmed transaction count and a
    one-sentence summary. Data comes from mempool.space and is read-only:
    this tool never holds keys, signs or broadcasts anything.
    """
    try:
        clean = validate_btc_address(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        raw = await get_client().get_address(clean)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc
    return BtcBalance.build(
        address=raw.address,
        confirmed_sats=raw.chain_stats.balance_sats,
        unconfirmed_sats=raw.mempool_stats.balance_sats,
        tx_count=raw.chain_stats.tx_count,
    )


def main() -> None:
    """Run the server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
