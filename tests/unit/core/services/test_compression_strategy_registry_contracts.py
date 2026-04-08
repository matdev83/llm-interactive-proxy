from __future__ import annotations

import logging

import pytest
from src.core.domain.configuration.dynamic_compression_config import CompressionLevel
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry


class _StubStrategy:
    def __init__(self, label: str) -> None:
        self.label = label

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        return f"{content}:{self.label}"


def test_register_duplicate_strategy_keeps_existing_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = CompressionStrategyRegistry()
    first = _StubStrategy("first")
    second = _StubStrategy("second")

    registry.register("line_dedupe", first)
    with caplog.at_level(
        logging.WARNING,
        logger="src.core.services.compression_strategy_registry",
    ):
        registry.register("line_dedupe", second)

    assert registry.get("line_dedupe") is first
    assert registry.available_method_names() == ["line_dedupe"]
    assert any("already registered" in record.message for record in caplog.records)


def test_register_duplicate_uses_normalized_method_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = CompressionStrategyRegistry()
    first = _StubStrategy("first")
    second = _StubStrategy("second")

    registry.register(" ansi_normalize ", first)
    with caplog.at_level(
        logging.WARNING,
        logger="src.core.services.compression_strategy_registry",
    ):
        registry.register("ansi_normalize", second)

    assert registry.get("ansi_normalize") is first
    assert registry.available_method_names() == ["ansi_normalize"]
    assert len(caplog.records) == 1
