import pytest

from stacks_mcp.errors import InvalidAddressError
from stacks_mcp.validation import validate_btc_address


@pytest.mark.parametrize(
    "address",
    [
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
        "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        "bc1p5cyxnuxmeuwuvkwfem96lqzszd02n6xdcjrs20cac6yqjjwudpxqkedrcr",
    ],
)
def test_accepts_mainnet_shapes(address: str) -> None:
    assert validate_btc_address(f"  {address} ") == address


def test_uppercase_bech32_is_lowercased() -> None:
    upper = "BC1QAR0SRRR7XFKVY5L643LYDNW9RE59GTZZWF5MDQ"
    assert validate_btc_address(upper) == upper.lower()


@pytest.mark.parametrize(
    "address",
    [
        "",
        "   ",
        "not-an-address",
        "0A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "1A1zP1eP5QGefi2DMPTfTL5SLmv7Div0Na",
        "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx",
        "bc1QAR0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
        "SP2J6ZY48GV1EZ5V2V5RB9MP66SW86PYKKNRV9EJ7",
    ],
)
def test_rejects_bad_shapes(address: str) -> None:
    with pytest.raises(InvalidAddressError):
        validate_btc_address(address)
