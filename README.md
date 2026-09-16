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

The server speaks MCP over stdio. Set `MEMPOOL_BASE_URL` to point at a self-hosted mempool instance (default `https://mempool.space/api`).

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

## Example: `explain_transaction`

<!-- TODO: paste a transcript of explain_transaction on a real mainnet tx once tool 5 lands. -->

_Coming with tool 5._

## Roadmap

1. `get_stx_balance(address)`: STX balance, locked amount, nonce (Hiro API).
2. `get_token_balances(address)`: SIP-10 fungible tokens including sBTC, with symbol, decimals and human-readable amount.
3. `get_recent_transactions(address, chain, limit=10)`: normalised list across BTC and STX.
4. `explain_transaction(txid, chain)`: deterministic plain-English decode of a transaction. No LLM inside the tool; the agent calling it is the LLM.
5. `draft_stx_transfer(sender, recipient, amount_ustx, memo?)`: unsigned transfer payload plus fee estimate.

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
