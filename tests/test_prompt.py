"""The `wallet_review` prompt, through the MCP protocol. No network."""

import pytest
import respx
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent

from stacks_mcp.server import mcp

from .conftest import GENESIS, SBTC_DEPLOYER


async def _render(arguments: dict[str, str]) -> str:
    async with Client(mcp) as client:
        result = await client.get_prompt("wallet_review", arguments)
    assert len(result.messages) == 1
    message = result.messages[0]
    assert message.role == "user"
    assert isinstance(message.content, TextContent)
    return message.content.text


async def test_the_prompt_is_registered_with_its_arguments() -> None:
    async with Client(mcp) as client:
        result = await client.list_prompts()
    prompts = {prompt.name: prompt for prompt in result.prompts}
    assert "wallet_review" in prompts
    review = prompts["wallet_review"]
    assert review.title == "Review a wallet for unusual activity"
    assert review.description is not None
    assert review.arguments is not None
    required = {argument.name for argument in review.arguments if argument.required}
    optional = {argument.name for argument in review.arguments if not argument.required}
    assert required == {"address"}
    assert optional == {"chain"}


async def test_the_prompt_reaches_no_upstream(mocked_http: respx.MockRouter) -> None:
    """Rendering is pure text. The model that receives it does the fetching."""
    await _render({"address": SBTC_DEPLOYER})
    assert not mocked_http.calls


async def test_a_stacks_review_points_at_the_resource_and_the_tools() -> None:
    text = await _render({"address": SBTC_DEPLOYER})
    assert f"stacks://address/{SBTC_DEPLOYER}/summary" in text
    assert 'get_recent_transactions(address="' + SBTC_DEPLOYER + '", chain="stx"' in text
    assert 'explain_transaction(txid=..., chain="stx")' in text


async def test_a_stacks_review_names_all_four_things_to_flag() -> None:
    text = await _render({"address": SBTC_DEPLOYER})
    assert "interacting with for the first time" in text
    assert "Dust-sized incoming Bitcoin" in text
    assert "large against this account's own history" in text
    assert "Failed transactions" in text


async def test_the_prompt_asks_for_no_analysis_of_its_own() -> None:
    """The caller is the model, so the prompt states no findings and no thresholds."""
    text = await _render({"address": SBTC_DEPLOYER})
    assert "not against any\n  fixed threshold" in text
    assert "do not state a conclusion\nthe data does not support" in text
    assert "If nothing is unusual, say so plainly." in text


async def test_a_bitcoin_review_uses_the_bitcoin_tools() -> None:
    text = await _render({"address": GENESIS, "chain": "btc"})
    assert f'get_btc_balance(address="{GENESIS}")' in text
    assert 'chain="btc"' in text
    assert "stacks://" not in text
    assert "Dust-sized incoming Bitcoin" in text


async def test_chain_defaults_to_stacks() -> None:
    assert await _render({"address": SBTC_DEPLOYER}) == await _render(
        {"address": SBTC_DEPLOYER, "chain": "stx"}
    )


async def test_a_malformed_address_is_rejected_with_its_reason(
    mocked_http: respx.MockRouter,
) -> None:
    """A plain exception would render as "Error rendering prompt"; the reason must survive."""
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("wallet_review", {"address": GENESIS})
    assert "Stacks principal" in str(caught.value)
    assert not mocked_http.calls


async def test_a_stacks_address_is_rejected_on_the_bitcoin_chain() -> None:
    async with Client(mcp) as client:
        with pytest.raises(MCPError) as caught:
            await client.get_prompt("wallet_review", {"address": SBTC_DEPLOYER, "chain": "btc"})
    assert "Bitcoin address" in str(caught.value)
