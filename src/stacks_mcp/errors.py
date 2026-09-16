"""Typed errors raised by the server and its clients."""


class UpstreamError(Exception):
    """An upstream API returned a non-2xx response or could not be reached."""

    def __init__(self, service: str, status_code: int | None, detail: str) -> None:
        self.service = service
        self.status_code = status_code
        self.detail = detail
        status = str(status_code) if status_code is not None else "no response"
        super().__init__(f"{service} request failed ({status}): {detail}")


class InvalidAddressError(ValueError):
    """The caller supplied an address that does not look like a valid address."""


class InvalidTxidError(ValueError):
    """The caller supplied a transaction id that does not look like one."""


class InvalidMemoError(ValueError):
    """The caller supplied a memo too long for a Stacks transfer."""


class InvalidAmountError(ValueError):
    """The caller supplied an amount that cannot be transferred."""
