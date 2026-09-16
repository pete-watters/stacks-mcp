# stacks-mcp

[![CI](https://github.com/pete-watters/stacks-mcp/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/pete-watters/stacks-mcp/actions/workflows/ci.yml)

A read-only [MCP](https://modelcontextprotocol.io) server that lets an AI agent answer questions about any Bitcoin or Stacks address: balances, transaction history, plain-English transaction explanations, and sBTC / SIP-10 token positions. Point Claude Desktop or Claude Code at it and ask "what has SP2... been doing this week?". It is a small Python service built on the official `mcp` SDK, `httpx` and `pydantic`, backed by the public mempool.space and Hiro APIs.

## Design principle: read-only

The server never holds keys, never signs and never broadcasts. Every tool reads public chain data and returns a typed Pydantic model plus a one-sentence summary. `draft_stx_transfer` returns an unsigned payload for a wallet to review, sign and send itself; that is the hard ceiling, and the payload carries no signature and no key. No secrets are needed to run it. Optional API keys can be supplied through environment variables to raise upstream rate limits.

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
| `draft_stx_transfer` | `sender` (standard principal), `recipient` (standard or contract principal), `amount_ustx`, `memo` (optional, 34 bytes) | an unsigned transfer payload: `signed` (always false), amounts in both units, the sender's next nonce, four fee tiers as absolute micro-STX, the sender's balance, plus a summary | Hiro API |

### Which upstream endpoints

Hiro's `/extended/v1` and `/extended/v2` address endpoints still answer but every
response carries a `warning: 299 - "Deprecated"` header, so this server uses the
current `/extended/v3/principals/...` endpoints for balances, nonces and
transactions, `/extended/v3/transactions/{txid}` and its `/events` for a single
transaction, and the Token Metadata API at `/metadata/v1/ft/{contract}` for
symbols and decimals. Fees come from `/extended/v2/mempool/fees`, which is the
only version of that endpoint and carries no deprecation warning, unlike its
v2 address neighbours. Token metadata is cached per process. A token the indexer
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

## Resource

| URI template | Returns | Source |
| --- | --- | --- |
| `stacks://address/{address}/summary` | `stx`, `tokens` and `transactions` for one Stacks principal, each the same shape its tool returns, plus `failures` and one summary covering all three | Hiro API |

One read replaces three tool calls. The three reads go out together with
`asyncio.gather`, and they degrade independently: an upstream failure leaves
that part `null`, names it in `failures` with the reason, and the rest of the
snapshot still arrives. A snapshot with nothing in it is still a result, not an
error, because "Hiro is down" is an answer the caller can act on.

## Prompt

| Name | Arguments | What it asks for |
| --- | --- | --- |
| `wallet_review` | `address`, `chain` (`stx` by default, or `btc`) | a review of one address's recent activity for anything unusual |

The prompt names the data to gather and the four things worth flagging, then
stops. It contains no analysis of its own and no thresholds, because the model
receiving it is the one that judges. On `stx` it points at the summary resource
and the Stacks tools; on `btc` at `get_btc_balance` and the Bitcoin tools.

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

## Example: the address summary resource

One read of the sBTC deployer, against the running stdio server on mainnet. The
transaction list is cut to two of its ten entries; everything else is verbatim.

```
> read_resource("stacks://address/SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4/summary")

{
  "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
  "stx": {
    "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
    "balance_ustx": 1965379994,
    "balance_stx": "1965.379994",
    "locked_ustx": 0,
    "locked_stx": "0.000000",
    "nonce": 3833,
    "summary": "SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833"
  },
  "tokens": {
    "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
    "tokens": [
      {
        "contract_id": "SP14XEKF7G8Q4WFYBSE77XSDMM67GTVF95R4V680.pixelstacks",
        "symbol": "pixelstacks",
        "decimals": 0,
        "balance_raw": "999000000",
        "balance": "999000000",
        "is_sbtc": false
      },
      {
        "contract_id": "SP37WN2BYHKZ90T1ATHTCNG8EFYHS3B49KNGS02ZK.RALEX",
        "symbol": "alexdao.org",
        "decimals": 0,
        "balance_raw": "154000",
        "balance": "154000",
        "is_sbtc": false
      },
      {
        "contract_id": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-token",
        "symbol": "sBTC",
        "decimals": 8,
        "balance_raw": "129",
        "balance": "0.00000129",
        "is_sbtc": true
      },
      {
        "contract_id": "SP1T0VY3DNXRVP6HBM75DFWW0199CR0X15PC1D81B.teiko-token-stxcity",
        "symbol": "Teiko",
        "decimals": 6,
        "balance_raw": "10000000",
        "balance": "10.000000",
        "is_sbtc": false
      }
    ],
    "summary": "SM3VDX...JFQ4 holds 4 fungible tokens: 999000000 pixelstacks, 154000 alexdao.org, 0.00000129 sBTC and 1 more; metadata unknown for 2 of them, shown in base units"
  },
  "transactions": {
    "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
    "chain": "stx",
    "transactions": [
      {
        "txid": "0xc2f1cefb6e463507fcdd00d8cf9f13a3c2166bdf3471735b62d45542152009f8",
        "chain": "stx",
        "timestamp": "2026-08-01T12:02:08Z",
        "direction": "in",
        "amount": "385.513100",
        "counterparty": "SP2ADT4TAV92SPBNP3WE9GPJ12F6CKGWMEJ1H1BB9",
        "status": "confirmed",
        "kind": "token_transfer"
      },
      {
        "txid": "0x577a7cfac2e54b0f5c29832730234a28dcfcce0b610c393baba5e3971c4c60c9",
        "chain": "stx",
        "timestamp": "2026-02-11T14:39:43Z",
        "direction": "out",
        "amount": "0.000000",
        "counterparty": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4.sbtc-bootstrap-signers",
        "status": "confirmed",
        "kind": "contract_call"
      }
      // ... eight more, newest first
    ],
    "summary": "SM3VDX...JFQ4 has 10 recent STX transactions (1 in, 9 out), most recent 2026-08-01T12:02:08Z"
  },
  "failures": [],
  "summary": "SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833; holds 4 fungible tokens: 999000000 pixelstacks, 154000 alexdao.org, 0.00000129 sBTC and 1 more; metadata unknown for 2 of them, shown in base units; has 10 recent STX transactions (1 in, 9 out), most recent 2026-08-01T12:02:08Z"
}
```

When one upstream call fails the snapshot keeps the rest. The same read again
with `HIRO_BASE_URL` pointed at a proxy that forwards to Hiro but answers 503
for `/balances/ft`, with the two healthy parts cut for length:

```
{
  "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
  "stx": {
    "address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
    "balance_ustx": 1965379994,
    "balance_stx": "1965.379994",
    "locked_ustx": 0,
    "locked_stx": "0.000000",
    "nonce": 3833,
    "summary": "SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833"
  },
  "tokens": null,
  "transactions": {
    // ... the same ten transactions as above
    "summary": "SM3VDX...JFQ4 has 10 recent STX transactions (1 in, 9 out), most recent 2026-08-01T12:02:08Z"
  },
  "failures": [
    {
      "part": "token balances",
      "reason": "Hiro API request failed (503): down"
    }
  ],
  "summary": "SM3VDX...JFQ4 holds 1965.379994 STX, none locked, next nonce 3833; has 10 recent STX transactions (1 in, 9 out), most recent 2026-08-01T12:02:08Z; could not read token balances"
}
```

## Example: the `wallet_review` prompt

Rendered against the same address, verbatim from the running server:

```
> get_prompt("wallet_review", {"address": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4"})

role: user

Review the recent activity of the Stacks address
SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4
and say whether anything about it looks unusual.

Gather the data first:

1. Read the resource stacks://address/SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4/summary
   One call gives the STX balance and lock state, every SIP-10 position
   including sBTC, and the 10 most recent transactions.
2. Call get_recent_transactions(address="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4", chain="stx", limit=50)
   for enough history to judge what is normal for this account.
3. Call explain_transaction(txid=..., chain="stx")
   on each transaction you want to describe or question.

Then look for these four things:

- Contracts this address is interacting with for the first time. Compare the
  contract ids in the newest transactions against the older ones, and say which
  contract and which txid.
- Dust-sized incoming Bitcoin: tiny unsolicited sBTC credits. Give the amount
  and the sender.
- Outflows that are large against this account's own history, not against any
  fixed threshold. Compare each outgoing amount to the balance and to the usual
  size of this address's own transfers.
- Failed transactions. A failed transaction paid a fee and did nothing, so say
  what it was trying to do.

Report what you found and what you checked and found nothing wrong
with. Cite the txid behind every claim, and do not state a conclusion
the data does not support. If nothing is unusual, say so plainly.
```

## Example: `draft_stx_transfer`

The one tool that produces something a wallet could act on. It is unsigned, and
the server holds no key.

```
> draft_stx_transfer(sender="SP2ADT4TAV92SPBNP3WE9GPJ12F6CKGWMEJ1H1BB9", recipient="SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4", amount_ustx=2500000, memo="invoice 42")

{
  "signed": false,
  "sender": "SP2ADT4TAV92SPBNP3WE9GPJ12F6CKGWMEJ1H1BB9",
  "recipient": "SM3VDXK3WZZSA84XXFKAFAF15NNZX32CTSG82JFQ4",
  "amount_ustx": 2500000,
  "amount_stx": "2.500000",
  "memo": "invoice 42",
  "nonce": 45438,
  "network": "mainnet",
  "fees": [
    { "priority": "no_priority", "fee_ustx": 240, "fee_stx": "0.000240" },
    { "priority": "low_priority", "fee_ustx": 300, "fee_stx": "0.000300" },
    { "priority": "medium_priority", "fee_ustx": 2458, "fee_stx": "0.002458" },
    { "priority": "high_priority", "fee_ustx": 4185, "fee_stx": "0.004185" }
  ],
  "sender_balance_ustx": 7223840809432,
  "sender_balance_stx": "7223840.809432",
  "summary": "Unsigned draft: SP2ADT...1BB9 would send 2.500000 STX to SM3VDX...JFQ4 at nonce 45438, fee 0.000240 STX and up; the balance of 7223840.809432 STX covers it. Not signed and not broadcast"
}
```

Every field is an input a wallet needs to build the transaction: it supplies the
public key, signs and broadcasts. There is no signature here and no serialised
transaction, so nothing this tool returns can move funds. Fees are absolute
micro-STX for a token transfer, taken from Hiro's mempool fee endpoint, not a
rate per byte. A contract principal is rejected as `sender`, because a contract
holds STX but has no key to sign with. The memo limit is 34 encoded bytes, so
nine emoji do not fit where 34 ASCII characters do.

The reported balance includes any STX locked by stacking, which cannot be
spent, so "the balance covers it" is a statement about the balance, not a
promise that the transfer will land.

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

Everything in the v1 scope has shipped: six tools, the address summary resource
and the `wallet_review` prompt. What is deliberately out of scope, and why, is
in [`DESIGN.md`](DESIGN.md): DeFi swap semantics, NFT marketplace internals and
multisig detail each need a per-protocol registry rather than a decoder. Each is
a candidate for v2, gated on someone asking for it.

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
