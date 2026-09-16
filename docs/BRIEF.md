# Brief: `stacks-mcp` — a read-only Bitcoin/Stacks MCP server in Python

## Why this exists

A small, standalone artefact that shows three things at once: Python backend competence, agentic/AI-native tooling (MCP is the protocol Claude, Cursor and Codex all speak), and Bitcoin/Stacks domain depth. It is deliberately separate from Stackr, which stays TypeScript-only and serverless.

It is a demo, not a product. Time-box: 2–3 days. Ship something small and polished over something big and half-done.

## What it does

An MCP server that lets an AI agent answer questions about any Bitcoin or Stacks address — balances, history, plain-English transaction explanations, sBTC and SIP-10 token positions — and draft (never sign) transactions. Point Claude Desktop or Claude Code at it and ask "what has SP2... been doing this week?".

## Non-negotiables

- **Read-only by default. Never holds keys, never signs, never broadcasts.** A `draft_*` tool may return an unsigned payload; that is the hard ceiling. Document this in the README as a design principle, not a limitation.
- **No secrets required to run.** Public APIs only (mempool.space, Hiro API). Optional API keys via env for rate limits.
- **Every tool returns structured, typed output** (Pydantic models) plus a short human summary string.
- **Testable offline.** All HTTP is mocked in tests with recorded fixtures. CI must pass with no network.

## Stack

- Python 3.12, `uv` for env and lockfile
- `mcp` (official Python SDK) — use `FastMCP` for tool registration; stdio transport first, HTTP/SSE transport as a stretch
- `httpx` (async) for upstream calls, `pydantic` v2 for models
- `ruff` (lint + format), `mypy --strict`, `pytest` + `pytest-asyncio` + `respx` for HTTP mocking
- GitHub Actions: lint, type-check, test on push and PR
- MIT licence

## Tools (v1 — build in this order)

1. `get_btc_balance(address)` — confirmed/unconfirmed sats, tx count. Source: mempool.space REST.
2. `get_stx_balance(address)` — STX balance, locked amount, nonce. Source: Hiro API.
3. `get_token_balances(address)` — SIP-10 fungible tokens incl. sBTC, with symbol, decimals, human-readable amount. Source: Hiro API.
4. `get_recent_transactions(address, chain, limit=10)` — normalised list across BTC and STX (hash, timestamp, direction, amount, counterparty, status).
5. `explain_transaction(txid, chain)` — the showpiece. Deterministic decode into plain English: "Contract call to `pox-4::stack-stx` locking 2,500 STX for 6 cycles", "sBTC deposit of 0.05 BTC", "Simple BTC transfer, 2 inputs, 3 outputs, fee 12 sat/vB". Decode the common cases explicitly; fall back to a structured summary for anything else. No LLM call inside the tool — the agent using the tool is the LLM.
6. `draft_stx_transfer(sender, recipient, amount_ustx, memo?)` — returns an unsigned transfer payload and a fee estimate. Stretch goal; skip if time is short.

## Resources and prompts (cheap wins)

- Resource: `stacks://address/{address}/summary` — one-call snapshot combining tools 1–4.
- Prompt: `wallet_review` — "review this address's activity for anything unusual" (new contracts interacted with, dust-sized incoming BTC, large outflows).

## Repo shape

```
stacks-mcp/
  src/stacks_mcp/
    server.py         # FastMCP app, tool registration
    clients/          # mempool.py, hiro.py — thin async clients
    models.py         # Pydantic output models
    decoders/         # btc.py, stacks.py — explain_transaction logic
  tests/
    fixtures/         # recorded JSON responses
    test_*.py
  README.md
  pyproject.toml
  .github/workflows/ci.yml
  CLAUDE.md
```

## README must include

- One-paragraph pitch and the read-only principle
- `uvx` / `uv run` one-liner to start it
- Claude Desktop and Claude Code config snippets (`mcpServers` JSON)
- A short transcript showing `explain_transaction` on a real mainnet tx
- Architecture note: why deterministic decoding rather than an LLM inside the tool

## Definition of done

- Tools 1–5 working against mainnet, with fixture-backed tests
- CI green, `ruff`, `mypy --strict` and `pytest` all pass
- README screenshots/transcript of it running inside Claude Desktop
- Tagged `v0.1.0`

## Working rules

- Verify current mempool.space and Hiro API endpoints and response shapes against their docs before writing clients; do not rely on memory of the schemas.
- Start with the mempool.space client and `get_btc_balance` end to end (client → model → tool → test → run in Claude Desktop) before adding anything else. Prove the loop, then widen.
- Keep each tool's docstring precise — it is what the agent reads to decide when to call it.
- Record real responses for fixtures once, then never hit the network in tests.
- Open a short RFC-style `DESIGN.md` for `explain_transaction` before implementing: which tx types are decoded explicitly, what the fallback looks like.
