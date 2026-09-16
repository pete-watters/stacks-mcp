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

### Which upstream endpoints

Hiro's `/extended/v1` and `/extended/v2` address endpoints still answer but every
response carries a `warning: 299 - "Deprecated"` header, so this server uses the
current `/extended/v3/principals/...` endpoints for balances, nonces and
transactions, and the Token Metadata API at `/metadata/v1/ft/{contract}` for
symbols and decimals. Token metadata is cached per process. A token the indexer
has no metadata for keeps its base-unit balance: the symbol falls back to the
contract name, decimals to 0, and the summary says how many are affected, so no
amount is silently misscaled.

Direction always describes value flow as seen by the queried address: `in`,
`out`, `self` when it is on both sides, and `other` when no value moved. A
Stacks contract call that only pays a fee reports `out` with an amount of `0`,
because the fee is not a transfer. Stacks results are confirmed transactions
only; Bitcoin results include mempool transactions, which have a `pending`
status and no timestamp.

## Example: `explain_transaction`

<!-- TODO: paste a transcript of explain_transaction on a real mainnet tx once tool 5 lands. -->

_Coming with tool 5._

## Roadmap

1. `explain_transaction(txid, chain)`: deterministic plain-English decode of a transaction. No LLM inside the tool; the agent calling it is the LLM.
2. `draft_stx_transfer(sender, recipient, amount_ustx, memo?)`: unsigned transfer payload plus fee estimate.

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
