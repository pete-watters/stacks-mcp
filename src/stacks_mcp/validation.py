"""Shape checks for addresses. No checksum verification; upstream rejects bad ones."""

from __future__ import annotations

import re

from stacks_mcp.errors import InvalidAddressError

# Base58Check: P2PKH starts with 1, P2SH with 3. 26 to 35 chars, no 0 O I l.
_BASE58_RE = re.compile(r"^[13][1-9A-HJ-NP-Za-km-z]{25,34}$")
# Bech32 / bech32m: bc1 prefix, then 8 to 87 chars from the bech32 alphabet.
_BECH32_RE = re.compile(r"^bc1[02-9ac-hj-np-z]{8,87}$")


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
