# DESIGN: `explain_transaction`

## Contract

Input: `txid` and `chain` (`"btc"` or `"stx"`). A txid is 64 hex characters, `0x`
prefix optional on Stacks. Anything else raises `ToolError` before any request.

Output: one `TransactionExplanation` — normalised `txid`, `chain`, a `kind` from
the tables below, the plain-English `summary`, a `detail` dict of decoded
specifics, a human `fee`, `status`, `block_height`, `timestamp`, and
`participants`: every address and contract with a role.

Decoding is **deterministic**: a decoder is a pure function from the upstream
response model, with no HTTP, clock or model call inside. The same bytes always
produce the same sentence.

Decoding is **total**: every transaction produces a useful explanation. An
unrecognised shape falls through to the fallback below; it never raises.
`ToolError` covers only a malformed txid and an upstream failure. A reverted
transaction keeps its decoded case and gains a `Failed: ` prefix.

## Why deterministic decoding, not an LLM inside the tool

The caller is already a model. A second one inside the tool would make the output
non-reproducible, add a key and a per-call cost to a server whose selling point
is needing neither, and make a wrong answer unauditable. A decoder is a table of
named predicates; each is a test.

## Stacks cases

Source: `GET /extended/v3/transactions/{txid}?include=function_args`, plus
`/events` when a contract call reports `event_count > 0`. First match wins.

| `kind` | Detection rule | Example sentence |
| --- | --- | --- |
| `stx_transfer` | `type == "token_transfer"` | `STX transfer of 385.513100 STX from SP2ADT...1BB9 to SM3VDX...JFQ4.` |
| `sbtc_withdrawal` | `ft_asset` `burn` on the sBTC contract | `sBTC withdrawal of 0.15000720 sBTC burned from SP3A7M...M51D via sbtc-withdrawal::initiate-withdrawal-request.` |
| `sbtc_deposit` | `ft_asset` `mint` on the sBTC contract, no burn | `sBTC deposit of 0.00098076 sBTC minted to SP2WS9...JF7A via sbtc-deposit::complete-deposit-wrapper.` |
| `sip10_transfer` | any `ft_asset` `transfer` | `SIP-10 transfer of 0.00000100 sBTC from SP20GP...QJE1 to SP2GHQ...SF3B via sbtc-token::transfer.` |
| `stacking` | boot-address `pox*`, function `stack-stx`, `delegate-stx`, `stack-increase` | `Stacking: SP14S2...KHCB locked 4491100.000000 STX for 1 cycle via pox-4::stack-stx.` |
| `contract_call` | `type == "contract_call"` | `Contract call sbtc-bootstrap-signers::rotate-keys-wrapper by SM3VDX...JFQ4 with 3 arguments: (list 0x024020d254667b90..., 0x0204cff1ade0cc7f74d1b5..., u10.` |
| `contract_deploy` | `type == "smart_contract"` | `Contract deploy of zip-064 by SP2VCQ...QF4N, Clarity version 4.` |
| `coinbase` | `type == "coinbase"` | `Coinbase: block reward for Stacks block 9004429.` |
| `tenure_change` | `type == "tenure_change"` | `Tenure change at Stacks block 9004613, cause extended_read_count.` |

Withdrawal precedes deposit because both withdrawal legs burn one sBTC asset and
mint the other: `initiate-withdrawal-request` burns `sbtc-token` and mints
`sbtc-token-locked`; `accept-withdrawal-request` does the reverse. A deposit only
mints. Only sBTC's decimals are known without a second request, so other SIP-10
amounts stay in base units.

The pox rule matches `pox`, `pox-4`, `pox-5` and later revisions; mainnet has
already moved to `pox-5`. Arguments arrive positionally, so each decoded function
has a named signature: `stack-stx(amount-ustx, pox-addr, start-burn-ht,
lock-period, …)` yields amount and cycle count; `delegate-stx(amount-ustx,
delegate-to, …)` and `stack-increase(increase-by, …)` have none and invent none.
Other pox functions fall to `contract_call`.

## Bitcoin cases

Source: `GET /api/tx/{txid}` from mempool.space. First match wins.

| `kind` | Detection rule | Example sentence |
| --- | --- | --- |
| `coinbase` | any coinbase input | `Coinbase: 3.19050441 BTC of block reward and fees paid to 6 outputs in block 967296.` |
| `consolidation` | 5+ inputs, exactly 1 output | `Consolidation: 51 inputs from 10 addresses swept into 1.37207743 BTC at bc1q6d...9l55, fee 24,829 sats (7.09 sat/vB).` |
| `batch_payment` | exactly 1 input, 5+ outputs | `Batch payment: 1 input split across 77 outputs to 72 addresses totalling 1.55202003 BTC, fee 270,500 sats (100.04 sat/vB).` |
| `self_send` | every output address is an input address | `Self-send: 0.05603261 BTC moved between 2 addresses the sender already controls, 3 inputs, 2 outputs, fee 55,381 sats (205.11 sat/vB).` |
| `btc_transfer` | anything else | `BTC transfer of 0.01310200 BTC to 2 addresses, 1 input, 2 outputs, fee 45,900 sats (300.00 sat/vB).` |

OP_RETURN is a modifier, not a case: it sets `detail["op_return"]` and appends
`, plus an OP_RETURN output`. Coinbase is exempt: every coinbase carries a
witness-commitment OP_RETURN, so saying so tells the reader nothing.

## Fee reporting

mempool.space returns `fee` in sats and `weight`, not vsize, so the decoder
computes `vsize = ceil(weight / 4)` and reports `24,829 sats (7.09 sat/vB)`.
Hiro's `fee_rate` is the absolute fee in micro-STX despite its name:
`0.003102 STX (3,102 uSTX)`.

## Fallback

With no match, `kind` is `unknown` and the summary uses fields every transaction
has: `Stacks poison_microblock transaction by SP2GHQ...SF3B, fee
0.000180 STX (180 uSTX), confirmed in block 9004255.` `detail` keeps the upstream
type.

## Not decoded in v1

- **DeFi swap semantics.** "Swapped 500 STX for 0.004 sBTC" needs per-protocol
  knowledge of ALEX, Velar, Bitflow and Arkadiko, each with its own functions and
  events. That is a protocol registry, not a decoder, and it goes stale the moment
  a protocol ships v2. The generic case still names contract and function.
- **NFT marketplace internals.** Listings, bids and royalties: same problem, more
  contracts.
- **Multisig detail.** "2 of 3 signatures" needs script parsing on Bitcoin and
  post-condition analysis on Stacks. `participants` already names every address.

Each is a v2 candidate, gated on a user asking.
