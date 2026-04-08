from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionMarkerConfig,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _build_messages(
    tool_outputs: list[str], *, command: str = "git status"
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for idx, output in enumerate(tool_outputs):
        tool_call_id = f"tc-{idx}"
        messages.append(
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id=tool_call_id,
                        function=FunctionCall(
                            name="shell",
                            arguments=f'{{"command":"{command}"}}',
                        ),
                    )
                ],
            )
        )
        messages.append(
            ChatMessage(
                role="tool",
                tool_call_id=tool_call_id,
                content=output,
            )
        )
    return messages


class _CountingResolver(ToolIdentityResolver):
    def __init__(self) -> None:
        super().__init__()
        self.lookup_build_calls = 0

    def build_tool_call_lookup(
        self,
        messages: Sequence[ChatMessage],
    ) -> dict[str, tuple[str, str | dict[str, Any] | None]]:
        self.lookup_build_calls += 1
        return super().build_tool_call_lookup(messages)


class _TrimStrategy:
    def __init__(self, *, sleep_seconds: float = 0.0) -> None:
        self._sleep_seconds = sleep_seconds
        self.calls = 0

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        self.calls += 1
        if self._sleep_seconds > 0:
            time.sleep(self._sleep_seconds)
        if len(content) <= 1:
            return content
        return content[:-1]


class _NoopStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        return content


@pytest.mark.asyncio
async def test_compress_messages_builds_tool_lookup_once_per_batch() -> None:
    resolver = _CountingResolver()
    service = ToolOutputCompressionService(identity_resolver=resolver)
    messages = _build_messages(["one", "two", "three"])

    result = await service.compress_messages(
        messages=messages,
        config=DynamicCompressionConfig(enabled=False, min_bytes=0),
    )

    assert resolver.lookup_build_calls == 1
    assert len(result.records) == 3


@pytest.mark.asyncio
async def test_time_budget_exceeded_stops_pipeline_and_records_reason() -> None:
    slow = _TrimStrategy(sleep_seconds=0.02)
    fast = _TrimStrategy()
    registry = CompressionStrategyRegistry()
    registry.register("slow", slow)
    registry.register("fast", fast)
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages(["abcdef"])
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        time_budget_ms_per_output=1,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"slow": True, "fast": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["slow", "fast"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    record = result.records[0]

    assert result.messages[1].content == "abcde"
    assert slow.calls == 1
    assert fast.calls == 0
    assert record.failed_open is True
    assert "time_budget_exceeded" in record.warnings
    assert any(
        method.skipped_reason == "time_budget_exceeded" for method in record.methods
    )


@pytest.mark.asyncio
async def test_long_pipeline_cooperatively_yields_to_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    yielded_calls = 0

    async def _fake_sleep(delay: float) -> None:
        nonlocal yielded_calls
        yielded_calls += 1

    monkeypatch.setattr(
        "src.core.services.tool_output_compression_service.asyncio.sleep",
        _fake_sleep,
    )

    registry = CompressionStrategyRegistry()
    registry.register("noop", _NoopStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages(["x" * 128])
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        time_budget_ms_per_output=60_000,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"noop": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["noop"] * 64,
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].failed_open is False
    assert yielded_calls > 0
