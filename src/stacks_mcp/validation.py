"""Shape checks for addresses. No checksum verification; upstream rejects bad ones."""

from __future__ import annotations

import re

from stacks_mcp.errors import InvalidAddressError

# Base58Check: P2PKH starts with 1, P2SH with 3. 26 to 35 chars, no 0 O I l.
_BASE58_RE = re.compile(r"^[13][1-9A-HJ-NP-Za-km-z]{25,34}$")
# Bech32 / bech32m: bc1 prefix, then 8 to 87 chars from the bech32 alphabet.
_BECH32_RE = re.compile(r"^bc1[02-9ac-hj-np-z]{8,87}$")
# Stacks mainnet c32check: SP (single-sig) or SM (multi-sig) prefix, then the c32
# alphabet (no I, L, O, U). 28 to 41 chars in total, matching the length range the
# Hiro metadata API validates. Short ones are real: BNS lives at
# SP000000000000000000002Q6VF78.bns because c32 trims leading zeros.
_STX_ADDRESS_RE = re.compile(r"^S[PM][0-9A-HJKMNP-TV-Z]{26,39}$")
# Contract name as the Hiro metadata API validates it: a letter, then up to 39 of
# letters, digits, hyphen or underscore.
_STX_CONTRACT_NAME_RE = re.compile(r"^[a-zA-Z]([a-zA-Z0-9]|[-_]){0,39}$")


def validate_btc_address(address: str) -> str:
    """Return the trimmed address or raise ``InvalidAddressError``.

    Accepts mainnet base58 (1..., 3...) and bech32 (bc1...) shapes only.
    """
    candidate = address.strip()
    if not candidate:
        raise InvalidAddressError("address is empty")
    if _BASE58_RE.match(candidate):
        return candidate
    lowered = candidate.lower()
    if _BECH32_RE.match(lowered) and candidate in (lowered, candidate.upper()):
        return lowered
    raise InvalidAddressError(
        f"'{candidate}' is not a mainnet Bitcoin address; expected one starting with 1, 3 or bc1"
    )


def validate_stx_principal(principal: str) -> str:
    """Return the trimmed principal or raise ``InvalidAddressError``.

    Accepts mainnet standard principals (``SP...`` or ``SM...``) and contract
    principals (``SP....name``). Contracts can hold STX and tokens, and the
    Hiro v3 ``principals`` endpoints accept both shapes.
    """
    candidate = principal.strip()
    if not candidate:
        raise InvalidAddressError("address is empty")
    address, dot, contract_name = candidate.partition(".")
    if _STX_ADDRESS_RE.match(address) and (not dot or _STX_CONTRACT_NAME_RE.match(contract_name)):
        return candidate
    raise InvalidAddressError(
        f"'{candidate}' is not a mainnet Stacks principal; expected one starting with SP or SM, "
        "optionally followed by .contract-name"
    )
