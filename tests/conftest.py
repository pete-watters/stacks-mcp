"""Shared fixtures. Every test runs with HTTP fully mocked; unmocked calls fail."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import respx

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> Any:
    return json.loads(FIXTURES.joinpath(*parts).read_text())


@pytest.fixture(autouse=True)
def mocked_http() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


@pytest.fixture
def genesis_fixture() -> Any:
    return load_fixture("mempool", "address_genesis.json")
