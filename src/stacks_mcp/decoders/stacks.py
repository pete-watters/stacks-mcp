"""Decode one Stacks transaction into plain English.

Every function here is pure: it reads a ``HiroTransactionDetail`` and the events
that transaction emitted, and returns a value. No HTTP, no clock, no model call,
so the same bytes always produce the same sentence. Detection lives in the small
named predicates below and the first match wins, so the order inside
:func:`decode_stacks_transaction` is the specification. `DESIGN.md` holds the
case table.
"""

from __future__ import annotations

import re

from stacks_mcp.clients.hiro import (
    HiroContractCall,
    HiroFtAssetEvent,
    HiroTransactionDetail,
    HiroTransactionEvent,
)
from stacks_mcp.models import (
    DetailValue,
    ExplainKind,
    Participant,
    TransactionExplanation,
    TxStatus,
    base_units_to_amount,
    short_address,
    unix_to_iso,
    ustx_to_stx,
)
from stacks_mcp.tokens import SBTC_CONTRACT_ID, contract_name

# sBTC tracks Bitcoin, so its base unit is the satoshi.
SBTC_DECIMALS = 8
# Boot contracts live at an address of padded zeroes; `pox`, `pox-4` and `pox-5`
# have all held the stacking logic, so the revision number is not pinned.
POX_BOOT_ADDRESS_PREFIX = "SP000000000000000000"
_POX_NAME_RE = re.compile(r"^pox(-\d+)?$")

# Hiro's v3 API returns contract-call arguments positionally, with no parameter
# names, so each decoded function carries its own signature. Taken from the
# mainnet pox-4 source; pox-5 keeps the same three signatures.
POX_SIGNATURES: dict[str, tuple[str, ...]] = {
    "stack-stx": (
        "amount-ustx",
        "pox-addr",
        "start-burn-ht",
        "lock-period",
        "signer-sig",
        "signer-key",
        "max-amount",
        "auth-id",
    ),
    "delegate-stx": ("amount-ustx", "delegate-to", "until-burn-ht", "pox-addr"),
    "stack-increase": ("increase-by", "signer-sig", "signer-key", "max-amount", "auth-id"),
}

# Enough arguments to recognise a call, not so many that the sentence stops
# being a sentence.
MAX_ARGUMENTS_SHOWN = 3
MAX_ARGUMENT_LENGTH = 24


def clarity_uint(value: str) -> int | None:
    """Parse a Clarity uint literal such as ``u4491100000000``."""
    if value.startswith("u") and value[1:].isdigit():
        return int(value[1:])
    return None


def clarity_principal(value: str) -> str | None:
    """Parse a Clarity principal literal such as ``'SP2GHQRCRMYY4S8PMBR49BEKX144VR437YT42SF3B``."""
    return value[1:] if value.startswith("'") and len(value) > 1 else None


def is_pox_contract(contract_id: str) -> bool:
    """True for the boot-address stacking contract of any revision."""
    address, _, name = contract_id.partition(".")
    return address.startswith(POX_BOOT_ADDRESS_PREFIX) and bool(_POX_NAME_RE.match(name))


def is_stx_transfer(tx: HiroTransactionDetail) -> bool:
    """True when the transaction moves STX and nothing else."""
    return tx.type == "token_transfer" and tx.token_transfer is not None


def is_contract_deploy(tx: HiroTransactionDetail) -> bool:
    return tx.type == "smart_contract" and tx.smart_contract is not None


def is_coinbase(tx: HiroTransactionDetail) -> bool:
    return tx.type == "coinbase"


def is_tenure_change(tx: HiroTransactionDetail) -> bool:
    return tx.type == "tenure_change" and tx.tenure_change is not None


def is_stacking_call(tx: HiroTransactionDetail) -> bool:
    """True for a pox call this decoder knows the signature of."""
    call = tx.contract_call
    if tx.type != "contract_call" or call is None:
        return False
    return is_pox_contract(call.contract_id) and call.function_name in POX_SIGNATURES


def sbtc_events(events: list[HiroTransactionEvent]) -> list[HiroFtAssetEvent]:
    """Fungible-token events emitted by the mainnet sBTC contract.

    Both the liquid ``sbtc-token`` asset and the ``sbtc-token-locked`` asset used
    mid-withdrawal live under that one contract, so the contract is the test
    rather than the asset name.
    """
    return [
        event.ft_asset
        for event in events
        if event.ft_asset is not None and event.ft_asset.contract_id == SBTC_CONTRACT_ID
    ]


def is_sbtc_withdrawal(events: list[HiroTransactionEvent]) -> bool:
    """True when sBTC left circulation.

    Checked before the deposit case: both legs of a withdrawal burn one sBTC
    asset and mint the other, while a deposit only ever mints.
    """
    return any(event.type == "burn" for event in sbtc_events(events))


def is_sbtc_deposit(events: list[HiroTransactionEvent]) -> bool:
    """True when sBTC entered circulation."""
    return any(event.type == "mint" for event in sbtc_events(events))


def first_ft_transfer(events: list[HiroTransactionEvent]) -> HiroFtAssetEvent | None:
    """The first SIP-10 transfer in the transaction, if there is one."""
    for event in events:
        if event.ft_asset is not None and event.ft_asset.type == "transfer":
            return event.ft_asset
    return None


def first_sbtc_event(events: list[HiroTransactionEvent], kind: str) -> HiroFtAssetEvent | None:
    for event in sbtc_events(events):
        if event.type == kind:
            return event
    return None


def format_fee(tx: HiroTransactionDetail) -> str:
    """The fee as a human string. Hiro's ``fee_rate`` is an absolute micro-STX fee."""
    fee = int(tx.fee_rate)
    return f"{ustx_to_stx(fee)} STX ({fee:,} uSTX)"


def tx_status(tx: HiroTransactionDetail) -> TxStatus:
    """Map Hiro's status onto the three states every tool in this server reports."""
    if tx.status == "success":
        return "confirmed"
    return "pending" if tx.status == "pending" else "failed"


def pox_argument(call: HiroContractCall, name: str) -> str | None:
    """The printable value of a named pox parameter, found by its position."""
    signature = POX_SIGNATURES.get(call.function_name)
    if signature is None or name not in signature:
        return None
    index = signature.index(name)
    if index >= len(call.function_args):
        return None
    return call.function_args[index].repr


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {plural or singular + 's'}"


def _short_argument(value: str) -> str:
    if len(value) <= MAX_ARGUMENT_LENGTH:
        return value
    return f"{value[:MAX_ARGUMENT_LENGTH]}..."


def _qualified(call_contract_id: str, function_name: str) -> str:
    """``contract-name::function-name``, dropping the address that prefixes it."""
    return f"{contract_name(call_contract_id)}::{function_name}"


def _confirmation(tx: HiroTransactionDetail) -> str:
    if tx.block is None:
        return "still unconfirmed"
    return (
        f"confirmed in block {tx.block.height}"
        if tx.status == "success"
        else (f"in block {tx.block.height}")
    )


def _sbtc_amount(raw: str) -> str:
    return base_units_to_amount(int(raw), SBTC_DECIMALS)


def _token_amount(event: HiroFtAssetEvent) -> str:
    """Scale sBTC by its known decimals; leave every other token in base units.

    Decimals for an arbitrary SIP-10 token would need a second request to the
    token metadata API, and a decoder makes no requests.
    """
    if event.contract_id == SBTC_CONTRACT_ID:
        return f"{_sbtc_amount(event.amount)} sBTC"
    return f"{int(event.amount):,} base units of {event.asset_name}"


def _stacking_sentence(tx: HiroTransactionDetail, call: HiroContractCall) -> str:
    who = short_address(tx.sender.address)
    where = _qualified(call.contract_id, call.function_name)
    if call.function_name == "stack-stx":
        amount = clarity_uint(pox_argument(call, "amount-ustx") or "")
        cycles = clarity_uint(pox_argument(call, "lock-period") or "")
        if amount is not None and cycles is not None:
            return (
                f"Stacking: {who} locked {ustx_to_stx(amount)} STX for "
                f"{_plural(cycles, 'cycle')} via {where}"
            )
    elif call.function_name == "delegate-stx":
        amount = clarity_uint(pox_argument(call, "amount-ustx") or "")
        delegate = clarity_principal(pox_argument(call, "delegate-to") or "")
        if amount is not None and delegate is not None:
            return (
                f"Stacking: {who} delegated up to {ustx_to_stx(amount)} STX to "
                f"{short_address(delegate)} via {where}"
            )
    else:
        increase = clarity_uint(pox_argument(call, "increase-by") or "")
        if increase is not None:
            return (
                f"Stacking: {who} added {ustx_to_stx(increase)} STX to an existing lock via {where}"
            )
    return f"Stacking: {who} called {where}, arguments not reported"


def _contract_call_sentence(tx: HiroTransactionDetail, call: HiroContractCall) -> str:
    who = short_address(tx.sender.address)
    where = _qualified(call.contract_id, call.function_name)
    args = call.function_args
    if not args:
        return f"Contract call {where} by {who} with no arguments"
    shown = ", ".join(_short_argument(arg.repr) for arg in args[:MAX_ARGUMENTS_SHOWN])
    extra = len(args) - MAX_ARGUMENTS_SHOWN
    more = f" and {extra} more" if extra > 0 else ""
    return f"Contract call {where} by {who} with {_plural(len(args), 'argument')}: {shown}{more}"


def _core(
    tx: HiroTransactionDetail, events: list[HiroTransactionEvent]
) -> tuple[ExplainKind, str, dict[str, DetailValue], list[Participant]]:
    """Pick the case, then build its sentence, detail and participants together."""
    sender = tx.sender.address
    call = tx.contract_call

    transfer = tx.token_transfer
    if is_stx_transfer(tx) and transfer is not None:
        memo = transfer.memo.repr.strip() if transfer.memo is not None else ""
        note = f' with memo "{memo}"' if memo else ""
        sentence = (
            f"STX transfer of {ustx_to_stx(int(transfer.amount))} STX from "
            f"{short_address(sender)} to {short_address(transfer.recipient)}{note}"
        )
        detail: dict[str, DetailValue] = {
            "amount_ustx": int(transfer.amount),
            "amount_stx": ustx_to_stx(int(transfer.amount)),
            "sender": sender,
            "recipient": transfer.recipient,
            "memo": memo or None,
        }
        return (
            "stx_transfer",
            sentence,
            detail,
            [
                Participant(address=sender, role="sender"),
                Participant(address=transfer.recipient, role="recipient"),
            ],
        )

    if call is not None and is_sbtc_withdrawal(events):
        burn = first_sbtc_event(events, "burn")
        if burn is not None:
            holder = burn.sender or sender
            where = _qualified(call.contract_id, call.function_name)
            sentence = (
                f"sBTC withdrawal of {_sbtc_amount(burn.amount)} sBTC burned from "
                f"{short_address(holder)} via {where}"
            )
            return (
                "sbtc_withdrawal",
                sentence,
                {
                    "amount_raw": int(burn.amount),
                    "amount_sbtc": _sbtc_amount(burn.amount),
                    "asset_identifier": burn.asset_identifier,
                    "holder": holder,
                    "contract_id": call.contract_id,
                    "function_name": call.function_name,
                },
                [
                    Participant(address=holder, role="sender"),
                    Participant(address=call.contract_id, role="contract"),
                ],
            )

    if call is not None and is_sbtc_deposit(events):
        mint = first_sbtc_event(events, "mint")
        if mint is not None and mint.recipient is not None:
            where = _qualified(call.contract_id, call.function_name)
            sentence = (
                f"sBTC deposit of {_sbtc_amount(mint.amount)} sBTC minted to "
                f"{short_address(mint.recipient)} via {where}"
            )
            return (
                "sbtc_deposit",
                sentence,
                {
                    "amount_raw": int(mint.amount),
                    "amount_sbtc": _sbtc_amount(mint.amount),
                    "asset_identifier": mint.asset_identifier,
                    "recipient": mint.recipient,
                    "contract_id": call.contract_id,
                    "function_name": call.function_name,
                },
                [
                    Participant(address=mint.recipient, role="recipient"),
                    Participant(address=call.contract_id, role="contract"),
                ],
            )

    moved = first_ft_transfer(events)
    if call is not None and moved is not None:
        from_address = moved.sender or sender
        to_address = moved.recipient or "an unnamed recipient"
        where = _qualified(call.contract_id, call.function_name)
        sentence = (
            f"SIP-10 transfer of {_token_amount(moved)} from {short_address(from_address)} "
            f"to {short_address(to_address)} via {where}"
        )
        return (
            "sip10_transfer",
            sentence,
            {
                "amount_raw": int(moved.amount),
                "asset_identifier": moved.asset_identifier,
                "token_contract_id": moved.contract_id,
                "is_sbtc": moved.contract_id == SBTC_CONTRACT_ID,
                "sender": from_address,
                "recipient": moved.recipient,
                "function_name": call.function_name,
            },
            [
                Participant(address=from_address, role="sender"),
                Participant(address=to_address, role="recipient"),
                Participant(address=moved.contract_id, role="contract"),
            ],
        )

    if call is not None and is_stacking_call(tx):
        lock = next((event.stx_lock for event in events if event.stx_lock is not None), None)
        amount = clarity_uint(pox_argument(call, "amount-ustx") or "") or clarity_uint(
            pox_argument(call, "increase-by") or ""
        )
        delegate = clarity_principal(pox_argument(call, "delegate-to") or "")
        participants = [
            Participant(address=sender, role="stacker"),
            Participant(address=call.contract_id, role="contract"),
        ]
        if delegate is not None:
            participants.append(Participant(address=delegate, role="delegate"))
        return (
            "stacking",
            _stacking_sentence(tx, call),
            {
                "contract_id": call.contract_id,
                "function_name": call.function_name,
                "amount_ustx": amount,
                "amount_stx": ustx_to_stx(amount) if amount is not None else None,
                "lock_period_cycles": clarity_uint(pox_argument(call, "lock-period") or ""),
                "delegate_to": delegate,
                "total_locked_ustx": int(lock.amount) if lock is not None else None,
                "unlock_bitcoin_height": lock.unlock_bitcoin_height if lock is not None else None,
            },
            participants,
        )

    if call is not None:
        return (
            "contract_call",
            _contract_call_sentence(tx, call),
            {
                "contract_id": call.contract_id,
                "function_name": call.function_name,
                "argument_count": len(call.function_args),
                "arguments": [arg.repr for arg in call.function_args[:MAX_ARGUMENTS_SHOWN]],
                "event_count": tx.event_count,
            },
            [
                Participant(address=sender, role="caller"),
                Participant(address=call.contract_id, role="contract"),
            ],
        )

    deploy = tx.smart_contract
    if is_contract_deploy(tx) and deploy is not None:
        version = (
            f", Clarity version {deploy.clarity_version}"
            if deploy.clarity_version is not None
            else ""
        )
        return (
            "contract_deploy",
            f"Contract deploy of {deploy.contract_name} by {short_address(sender)}{version}",
            {"contract_id": deploy.contract_id, "clarity_version": deploy.clarity_version},
            [
                Participant(address=sender, role="deployer"),
                Participant(address=deploy.contract_id, role="contract"),
            ],
        )

    if is_coinbase(tx):
        height = tx.block.height if tx.block is not None else None
        alt = tx.coinbase.alt_recipient if tx.coinbase is not None else None
        where = f"Stacks block {height}" if height is not None else "an unconfirmed Stacks block"
        paid = f", paid to {short_address(alt)}" if alt is not None else ""
        participants = [Participant(address=sender, role="miner")]
        if alt is not None:
            participants.append(Participant(address=alt, role="recipient"))
        return (
            "coinbase",
            f"Coinbase: block reward for {where}{paid}",
            {"alt_recipient": alt, "block_height": height},
            participants,
        )

    tenure = tx.tenure_change
    if is_tenure_change(tx) and tenure is not None:
        height = tx.block.height if tx.block is not None else None
        where = f"Stacks block {height}" if height is not None else "an unconfirmed Stacks block"
        return (
            "tenure_change",
            f"Tenure change at {where}, cause {tenure.cause}",
            {"cause": tenure.cause, "block_height": height},
            [Participant(address=sender, role="miner")],
        )

    return (
        "unknown",
        f"Stacks {tx.type} transaction by {short_address(sender)}, fee {format_fee(tx)}, "
        f"{_confirmation(tx)}",
        {"upstream_type": tx.type, "event_count": tx.event_count},
        [Participant(address=sender, role="sender")],
    )


def decode_stacks_transaction(
    tx: HiroTransactionDetail, events: list[HiroTransactionEvent] | None = None
) -> TransactionExplanation:
    """Decode one Stacks transaction. Total: never raises, always explains.

    ``events`` is what the transaction emitted. Pass an empty list when the
    transaction emitted none; the sBTC and SIP-10 cases simply will not match.
    A transaction that reverted keeps the case it was trying to be and gains a
    ``Failed: `` prefix, so the summary says what was attempted and ``status``
    says it did not land.
    """
    kind, sentence, detail, participants = _core(tx, events or [])
    status = tx_status(tx)
    if status == "failed":
        sentence = f"Failed: {sentence}"
    if tx.sponsor is not None:
        participants.append(Participant(address=tx.sponsor.address, role="sponsor"))
    return TransactionExplanation(
        txid=tx.tx_id,
        chain="stx",
        kind=kind,
        summary=f"{sentence}.",
        detail=detail,
        fee=format_fee(tx),
        status=status,
        block_height=tx.block.height if tx.block is not None else None,
        timestamp=unix_to_iso(tx.block.time) if tx.block is not None else None,
        participants=participants,
    )
