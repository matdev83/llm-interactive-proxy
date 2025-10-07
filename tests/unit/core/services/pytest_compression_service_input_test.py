from __future__ import annotations

import pytest
from src.core.services.pytest_compression_service import PytestCompressionService


@pytest.fixture()
def service() -> PytestCompressionService:
    return PytestCompressionService()


def test_scan_for_pytest_detects_input_string(
    service: PytestCompressionService,
) -> None:
    arguments = {"input": "pytest -q"}

    result = service.scan_for_pytest("bash", arguments)

    assert result is not None
    detected, command = result
    assert detected is True
    assert command == "pytest -q"
