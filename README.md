# stacks-mcp

A read-only [MCP](https://modelcontextprotocol.io) server that lets an AI agent answer questions about any Bitcoin or Stacks address: balances, transaction history, plain-English transaction explanations, and sBTC / SIP-10 token positions. Point Claude Desktop or Claude Code at it and ask "what has SP2... been doing this week?". It is a small Python service built on the official `mcp` SDK, `httpx` and `pydantic`, backed by the public mempool.space and Hiro APIs.

## Design principle: read-only

The server never holds keys, never signs and never broadcasts. Every tool reads public chain data and returns a typed Pydantic model plus a one-sentence summary. A future `draft_*` tool may return an unsigned payload for a wallet to review; that is the hard ceiling. No secrets are needed to run it. Optional API keys can be supplied through environment variables to raise upstream rate limits.

## Run it

From a checkout:

```sh
uv run stacks-mcp
```

Straight from GitHub, no clone:

```sh
uvx --from git+https://github.com/pete-watters/stacks-mcp stacks-mcp
```

The server speaks MCP over stdio and needs no configuration.

| Env var | Default | Purpose |
| --- | --- | --- |
| `MEMPOOL_BASE_URL` | `https://mempool.space/api` | Point at a self-hosted mempool instance. |
| `HIRO_BASE_URL` | `https://api.hiro.so` | Point at a self-hosted Stacks API. |
| `HIRO_API_KEY` | unset | Sent as the `x-api-key` header. Optional: it raises Hiro's rate limits, which are otherwise 20 requests a second and 50 a minute per IP. Get one at [platform.hiro.so](https://platform.hiro.so). |

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "stacks-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/pete-watters/stacks-mcp", "stacks-mcp"]
    }
  }
}
```

### Claude Code

```sh
claude mcp add stacks-mcp -- uvx --from git+https://github.com/pete-watters/stacks-mcp stacks-mcp
```

## Tools

| Tool | Input | Returns | Source |
| --- | --- | --- | --- |
| `get_btc_balance` | `address` (1..., 3... or bc1...) | confirmed and unconfirmed sats, confirmed BTC (8 dp), tx count, summary | mempool.space |
| `get_stx_balance` | `address` (SP..., SM... or SP....contract-name) | balance in micro-STX and STX (6 dp), locked amount in both units, next nonce, summary | Hiro API |
| `get_token_balances` | `address` (SP..., SM... or SP....contract-name) | one entry per SIP-10 token: contract id, symbol, decimals, base-unit and human balance, `is_sbtc` flag, plus a summary | Hiro API |
| `get_recent_transactions` | `address`, `chain` (`btc` or `stx`), `limit` (1–50, default 10) | normalised transactions: txid, ISO 8601 UTC timestamp (null while unconfirmed), direction, amount in BTC or STX, counterparty, status, kind, plus a summary | mempool.space, Hiro API |
| `explain_transaction` | `txid` (64 hex, `0x` optional on Stacks), `chain` (`btc` or `stx`) | one decoded transaction: `kind`, a plain-English `summary`, `detail` of the decoded specifics, human `fee`, `status`, `block_height`, `timestamp` and `participants` with a role each | mempool.space, Hiro API |

### Which upstream endpoints

Hiro's `/extended/v1` and `/extended/v2` address endpoints still answer but every
response carries a `warning: 299 - "Deprecated"` header, so this server uses the
current `/extended/v3/principals/...` endpoints for balances, nonces and
transactions, `/extended/v3/transactions/{txid}` and its `/events` for a single
transaction, and the Token Metadata API at `/metadata/v1/ft/{contract}` for
symbols and decimals. Token metadata is cached per process. A token the indexer
has no metadata for keeps its base-unit balance: the symbol falls back to the
contract name, decimals to 0, and the summary says how many are affected, so no
amount is silently misscaled.

A single transaction is fetched with `?include=function_args`, because Hiro omits
contract-call arguments by default and without them a `stack-stx` call cannot say
how much STX it locked. Events are a second request, so `explain_transaction`
makes it only when a contract call reports `event_count > 0`.

Direction always describes value flow as seen by the queried address: `in`,
`out`, `self` when it is on both sides, and `other` when no value moved. A
Stacks contract call that only pays a fee reports `out` with an amount of `0`,
because the fee is not a transfer. Stacks results are confirmed transactions
only; Bitcoin results include mempool transactions, which have a `pending`
status and no timestamp.

## Example: `explain_transaction`

Two real mainnet transactions, called against the running stdio server. A pox-4
stacking lock:

```
> explain_transaction(txid="0x995fb653065c74596b63e6cc9c10fb8fa7b8f3574d5ea089b45d3e11d9e7336e", chain="stx")

{
  "txid": "0x995fb653065c74596b63e6cc9c10fb8fa7b8f3574d5ea089b45d3e11d9e7336e",
  "chain": "stx",
  "kind": "stacking",
  "summary": "Stacking: SP14S2...KHCB locked 4491100.000000 STX for 1 cycle via pox-4::stack-stx.",
  "detail": {
    "contract_id": "SP000000000000000000002Q6VF78.pox-4",
    "function_name": "stack-stx",
    "amount_ustx": 4491100000000,
    "amount_stx": "4491100.000000",
    "lock_period_cycles": 1,
    "delegate_to": null,
    "total_locked_ustx": 4491100000000,
    "unlock_bitcoin_height": 962150
  },
  "fee": "0.003102 STX (3,102 uSTX)",
  "status": "confirmed",
  "block_height": 8647822,
  "timestamp": "2026-07-27T18:39:09Z",
  "participants": [
    { "address": "SP14S259H3AC9PXWJ8EVX9ER5NZ58R03GR4QAKHCB", "role": "stacker" },
    { "address": "SP000000000000000000002Q6VF78.pox-4", "role": "contract" }
  ]
}
```

An sBTC deposit, where the amount comes from the mint event rather than the call:

```
> explain_transaction(txid="0xd044e48842e5ba34e1d05bebd8e0a9519192624d61114848460dcba4c9611db6", chain="stx")

{
  "txid": "0xd044e48842e5ba34e1d05bebd8e0a9519192624d61114848460dcba4c9611db6",
  "chain": "stx",
  "kind": "sbtc_deposit",
  "summary": "sBTC deposit of 0.00098076 sBTC minted to SP2WS9...JF7A via sbtc-deposit::complete-deposit-wrapper.",
  "detail": {
    "amount_raw": 98076,
    "amount_sbtc": "0.00098076",
    "asset_identifier": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token::sbtc-token",
    "recipient": "SP2WS9QFNR8VMJZY6VWWFZNPKN7ZTVP746BMXJF7A",
    "contract_id": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-deposit",
    "function_name": "complete-deposit-wrapper"
  },
  "fee": "0.002079 STX (2,079 uSTX)",
  "status": "confirmed",
  "block_height": 6482551,
  "timestamp": "2026-02-11T13:27:23Z",
  "participants": [
    { "address": "SP2WS9QFNR8VMJZY6VWWFZNPKN7ZTVP746BMXJF7A", "role": "recipient" },
    { "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-deposit", "role": "contract" }
  ]
}
```

### Which cases are decoded

On Stacks: STX transfer, SIP-10 transfer, sBTC deposit, sBTC withdrawal, pox
stacking (`stack-stx`, `delegate-stx`, `stack-increase`), contract call, contract
deploy, coinbase and tenure change. On Bitcoin: coinbase, consolidation, batch
payment, self-send and plain transfer, with an OP_RETURN noted where one is
present. First match wins, and the order is the specification.

Decoding is total: an unrecognised shape falls through to a structured summary
built from the fields every transaction has, so the tool never fails to explain.
A transaction that reverted keeps the case it was trying to be and gains a
`Failed: ` prefix, so the summary says what was attempted and `status` says it did
not land. `ToolError` covers only two things: a malformed txid, rejected before
any request, and an upstream failure. [`DESIGN.md`](DESIGN.md) holds the full
case table and the rules behind each one.

## Architecture: deterministic decoding, not a model inside the tool

`explain_transaction` decodes with a table of named rules. There is no LLM call
anywhere inside it. Four reasons:

- **The caller is already a model.** An agent invoking this tool is the language
  model. A second one inside the tool adds a layer that the first one can already
  do, and does it with less context.
- **Reproducibility.** The same transaction always yields the same sentence. A
  test can assert the exact string; with a model in the loop it could only assert
  a vague shape, and would then miss real regressions.
- **No key, no cost, no latency.** The server's selling point is that it runs with
  no secrets. A model inside the tool would need an API key and charge per call
  for work that a few hundred lines of Python do for free.
- **A wrong answer stays auditable.** A decoder is a table of predicates, so a bad
  sentence is a named rule to read and a test to write. A wrong answer from a
  model is a prompt to tune and nothing to point at.

The cost is honest: cases nobody wrote a rule for get the fallback rather than a
guess. That is the right trade for a tool an agent must be able to trust. DeFi
swap semantics, NFT marketplace internals and multisig detail are deliberately
out of scope for v1; `DESIGN.md` says why for each.

## Roadmap

1. `draft_stx_transfer(sender, recipient, amount_ustx, memo?)`: unsigned transfer payload plus fee estimate.

## Development

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy --strict src
uv run pytest
```

Tests never touch the network. Upstream responses are recorded once under `tests/fixtures/` and replayed with `respx`.

## Licence

MIT. See [LICENSE](LICENSE).
