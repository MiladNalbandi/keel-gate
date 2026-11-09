from __future__ import annotations

import pytest

from keel_gate.domain.manifest import Manifest
from keel_gate.gate import Gate
from tests.factories import TEST_TOOLS


@pytest.fixture
def manifest() -> Manifest:
    return Manifest.from_mapping(TEST_TOOLS)


@pytest.fixture
def gate(manifest: Manifest) -> Gate:
    return Gate(manifest)
