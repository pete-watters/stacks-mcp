"""MCP application: tool, resource and prompt registration."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer, Message, UserMessage
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

from stacks_mcp import __version__
from stacks_mcp.clients.hiro import HiroTransactionEvent
from stacks_mcp.clients.hiro import get_client as get_hiro_client
from stacks_mcp.clients.mempool import get_client
from stacks_mcp.decoders.btc import decode_btc_transaction
from stacks_mcp.decoders.stacks import decode_stacks_transaction
from stacks_mcp.errors import (
    InvalidAddressError,
    InvalidMemoError,
    InvalidTxidError,
    UpstreamError,
)
from stacks_mcp.models import (
    AddressSummary,
    BtcBalance,
    Chain,
    RecentTransactions,
    StxBalance,
    StxTransferDraft,
    TokenBalances,
    TransactionExplanation,
)
from stacks_mcp.queries import (
    SUMMARY_TRANSACTION_LIMIT,
    fetch_address_summary,
    fetch_btc_balance,
    fetch_btc_transactions,
    fetch_stx_balance,
    fetch_stx_transactions,
    fetch_stx_transfer_draft,
    fetch_token_balances,
)
from stacks_mcp.validation import (
    validate_btc_address,
    validate_memo,
    validate_stx_principal,
    validate_stx_sender,
    validate_txid,
)

MAX_TRANSACTION_LIMIT = 50
NOT_FOUND = 404
ADDRESS_SUMMARY_URI = "stacks://address/{address}/summary"

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
        return await fetch_btc_balance(clean)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_stx_balance(address: str) -> StxBalance:
    """Get the STX balance of a Stacks mainnet principal.

    Call this when the user asks how much STX an address holds, how much of it
    is locked by stacking, or what its next nonce is. Accepts standard
    principals (SP... or SM...) and contract principals (SP....contract-name).

    Returns the total balance in micro-STX and STX (6 decimal places), the
    locked amount in both units, the next usable nonce and a one-sentence
    summary. Data comes from the Hiro API and is read-only: this tool never
    holds keys, signs or broadcasts anything.
    """
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        return await fetch_stx_balance(principal)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_token_balances(address: str) -> TokenBalances:
    """List the SIP-10 fungible tokens a Stacks mainnet principal holds.

    Call this when the user asks about token positions, sBTC holdings, or what
    a Stacks address owns beyond STX. Accepts standard principals (SP... or
    SM...) and contract principals (SP....contract-name).

    Each position gives the token contract id, its symbol and decimals, the
    balance in base units and the same balance scaled for humans, plus an
    `is_sbtc` flag for the mainnet sBTC contract. When a token's metadata is
    unknown the symbol falls back to the contract name, decimals to 0, and the
    balance stays in base units; the summary says how many are affected. Data
    comes from the Hiro API and is read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        return await fetch_token_balances(principal)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_recent_transactions(
    address: str, chain: Chain, limit: int = 10
) -> RecentTransactions:
    """List recent transactions of a Bitcoin or Stacks address, newest first.

    Call this when the user asks what an address has been doing lately, who it
    paid, or whether anything is pending. Set `chain` to "btc" for a Bitcoin
    address (1..., 3... or bc1...) or "stx" for a Stacks principal (SP..., SM...
    or SP....contract-name). `limit` is 1 to 50 and defaults to 10.

    Each entry gives the transaction id, block time as ISO 8601 UTC (null while
    unconfirmed), the direction as seen by the queried address ("in", "out",
    "self" or "other"), the amount in BTC or STX, the counterparty address or
    contract id, the status and what the transaction did. Bitcoin data comes
    from mempool.space and Stacks data from the Hiro API, which returns
    confirmed transactions only. Read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    if limit < 1 or limit > MAX_TRANSACTION_LIMIT:
        raise ToolError(f"limit must be between 1 and {MAX_TRANSACTION_LIMIT}, got {limit}")
    if chain == "btc":
        try:
            clean = validate_btc_address(address)
        except InvalidAddressError as exc:
            raise ToolError(str(exc)) from exc
        try:
            return await fetch_btc_transactions(clean, limit)
        except UpstreamError as exc:
            raise ToolError(str(exc)) from exc
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    try:
        return await fetch_stx_transactions(principal, limit)
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc


def _transaction_error(exc: UpstreamError, chain: Chain, txid: str) -> str:
    """Turn an upstream failure into something a caller can act on.

    A 404 means the id is well formed but no such transaction exists, which is a
    different problem from the API being down, so it gets its own wording.
    """
    if exc.status_code == NOT_FOUND:
        label = "Bitcoin" if chain == "btc" else "Stacks"
        return f"no {label} transaction found with id {txid}"
    return str(exc)


@mcp.tool()
async def explain_transaction(txid: str, chain: Chain) -> TransactionExplanation:
    """Explain one Bitcoin or Stacks transaction in plain English.

    Call this when the user asks what a transaction did, what a txid means, or
    to check whether a transfer, a stacking lock or an sBTC deposit went
    through. Set `chain` to "btc" or "stx". A txid is 64 hex characters, with or
    without a `0x` prefix on Stacks.

    Decoding is deterministic and total: it is a table of rules, not a language
    model, so the same transaction always gives the same answer, and an
    unrecognised shape still returns a structured summary rather than an error.
    Stacks cases decoded by name: STX transfer, SIP-10 and sBTC transfer, sBTC
    deposit and withdrawal, pox stacking (`stack-stx`, `delegate-stx`,
    `stack-increase`), contract call, contract deploy, coinbase and tenure
    change. Bitcoin cases: simple transfer, consolidation, batch payment,
    self-send and coinbase, with an OP_RETURN noted where present.

    Returns `kind` (which case matched), `summary` (the sentence), `detail` (the
    decoded specifics), `fee` (sat/vB on Bitcoin, STX and uSTX on Stacks),
    `status`, `block_height`, `timestamp` and `participants` (addresses and
    contracts with a role each). Bitcoin data comes from mempool.space and
    Stacks data from the Hiro API. Read-only: this tool never holds keys, signs
    or broadcasts anything.
    """
    try:
        clean = validate_txid(txid, chain)
    except InvalidTxidError as exc:
        raise ToolError(str(exc)) from exc
    if chain == "btc":
        try:
            btc_tx = await get_client().get_transaction(clean)
        except UpstreamError as exc:
            raise ToolError(_transaction_error(exc, chain, clean)) from exc
        return decode_btc_transaction(btc_tx)
    client = get_hiro_client()
    try:
        stx_tx = await client.get_transaction(clean)
        events: list[HiroTransactionEvent] = []
        # Events are a second request, so only ask when a contract call has any.
        # Nothing else this decoder handles needs them.
        if stx_tx.type == "contract_call" and stx_tx.event_count > 0:
            events = (await client.get_transaction_events(clean)).results
    except UpstreamError as exc:
        raise ToolError(_transaction_error(exc, chain, clean)) from exc
    return decode_stacks_transaction(stx_tx, events)


@mcp.tool()
async def draft_stx_transfer(
    sender: str, recipient: str, amount_ustx: int, memo: str | None = None
) -> StxTransferDraft:
    """Draft an unsigned STX transfer for a wallet to review, sign and send itself.

    This tool neither signs nor broadcasts anything.
    The caller holds no key, and this server holds none either.
    It reads public data and returns the inputs a wallet needs to build the
    transaction: the sender's next nonce, current fee tiers, and the amount and
    recipient as given. Signing and broadcasting happen in the user's wallet,
    never here. Nothing this tool returns can move funds.

    Call this when the user asks what a transfer would cost, what nonce it would
    use, or wants a transfer prepared for their wallet. `sender` must be a
    standard principal (SP... or SM...): a contract has no key and cannot sign.
    `recipient` may be a standard or a contract principal. `amount_ustx` is in
    micro-STX and must be at least 1; 1 STX is 1,000,000 micro-STX. `memo` is
    optional and holds at most 34 bytes once encoded.

    Returns `signed`, which is always false, the sender, recipient and amount in
    both units, the memo, the nonce, the network, four fee tiers as absolute
    micro-STX amounts, the sender's balance and a one-sentence summary. Fees
    come from Hiro's mempool fee endpoint for token transfers. The balance
    includes any STX locked by stacking, which cannot be spent, so a balance
    that covers the amount is not a promise that the transfer will land.
    """
    try:
        clean_sender = validate_stx_sender(sender)
        clean_recipient = validate_stx_principal(recipient)
    except InvalidAddressError as exc:
        raise ToolError(str(exc)) from exc
    if amount_ustx < 1:
        raise ToolError(f"amount_ustx must be at least 1 micro-STX, got {amount_ustx}")
    clean_memo: str | None = None
    if memo is not None:
        try:
            clean_memo = validate_memo(memo)
        except InvalidMemoError as exc:
            raise ToolError(str(exc)) from exc
    try:
        return await fetch_stx_transfer_draft(
            clean_sender, clean_recipient, amount_ustx, clean_memo
        )
    except UpstreamError as exc:
        raise ToolError(str(exc)) from exc


@mcp.resource(
    ADDRESS_SUMMARY_URI,
    name="stacks_address_summary",
    title="Stacks address summary",
    mime_type="application/json",
)
async def address_summary(address: str) -> AddressSummary:
    """A whole Stacks principal in one read: STX, tokens and recent transactions.

    Read this instead of calling `get_stx_balance`, `get_token_balances` and
    `get_recent_transactions` one after another. `{address}` is a mainnet
    principal (SP..., SM... or SP....contract-name).

    Returns the STX balance and lock state, every SIP-10 position including
    sBTC, the 10 most recent confirmed transactions, and a one-sentence summary
    covering all three. The three reads run concurrently and independently: if
    one upstream call fails, that part is null, `failures` names it with the
    reason, and the rest of the snapshot still arrives. Data comes from the Hiro
    API and is read-only: reading this never holds keys, signs or broadcasts
    anything.
    """
    try:
        principal = validate_stx_principal(address)
    except InvalidAddressError as exc:
        raise ResourceError(str(exc)) from exc
    return await fetch_address_summary(principal)


_STX_GATHER = f"""\
1. Read the resource stacks://address/{{address}}/summary
   One call gives the STX balance and lock state, every SIP-10 position
   including sBTC, and the {SUMMARY_TRANSACTION_LIMIT} most recent transactions.
2. Call get_recent_transactions(address="{{address}}", chain="stx", limit=50)
   for enough history to judge what is normal for this account.
3. Call explain_transaction(txid=..., chain="stx")
   on each transaction you want to describe or question."""

_BTC_GATHER = """\
1. Call get_btc_balance(address="{address}")
   for the confirmed balance, the unconfirmed change and the lifetime
   transaction count.
2. Call get_recent_transactions(address="{address}", chain="btc", limit=50)
   for enough history to judge what is normal for this address.
3. Call explain_transaction(txid=..., chain="btc")
   on each transaction you want to describe or question."""

_STX_FLAGS = """\
- Contracts this address is interacting with for the first time. Compare the
  contract ids in the newest transactions against the older ones, and say which
  contract and which txid.
- Dust-sized incoming Bitcoin: tiny unsolicited sBTC credits. Give the amount
  and the sender.
- Outflows that are large against this account's own history, not against any
  fixed threshold. Compare each outgoing amount to the balance and to the usual
  size of this address's own transfers.
- Failed transactions. A failed transaction paid a fee and did nothing, so say
  what it was trying to do."""

_BTC_FLAGS = """\
- Counterparties this address is transacting with for the first time. Compare
  the addresses in the newest transactions against the older ones, and say
  which address and which txid.
- Dust-sized incoming Bitcoin: tiny unsolicited outputs paid to this address.
  Give the amount and the funding input.
- Outflows that are large against this address's own history, not against any
  fixed threshold. Compare each outgoing amount to the balance and to the usual
  size of this address's own spends.
- Transactions still unconfirmed, and how long they have been waiting."""


@mcp.prompt(name="wallet_review", title="Review a wallet for unusual activity")
def wallet_review(address: str, chain: Chain = "stx") -> list[Message]:
    """Review one address's recent activity and flag anything unusual.

    Use this when the user wants a wallet looked over rather than one figure
    read off it. `address` is a Stacks principal or a Bitcoin address; `chain`
    is "stx" (the default) or "btc".

    The prompt names the data to gather and the four things worth flagging:
    first-time counterparties or contracts, dust-sized incoming Bitcoin,
    outflows that are large for this account's own history, and transactions
    that failed or are still waiting. It carries no findings of its own: the
    model that receives it calls the tools and does the judging.
    """
    label = "Stacks" if chain == "stx" else "Bitcoin"
    try:
        clean = validate_stx_principal(address) if chain == "stx" else validate_btc_address(address)
    except InvalidAddressError as exc:
        # A prompt has no ToolError equivalent, and any plain exception is
        # rewritten to "Error rendering prompt". MCPError keeps the sentence.
        raise MCPError(INVALID_PARAMS, str(exc)) from exc
    gather = (_STX_GATHER if chain == "stx" else _BTC_GATHER).format(address=clean)
    flags = _STX_FLAGS if chain == "stx" else _BTC_FLAGS
    return [
        UserMessage(
            f"Review the recent activity of the {label} address\n{clean}\n"
            f"and say whether anything about it looks unusual.\n\n"
            f"Gather the data first:\n\n{gather}\n\n"
            f"Then look for these four things:\n\n{flags}\n\n"
            f"Report what you found and what you checked and found nothing wrong\n"
            f"with. Cite the txid behind every claim, and do not state a conclusion\n"
            f"the data does not support. If nothing is unusual, say so plainly."
        )
    ]


def main() -> None:
    """Run the server over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
