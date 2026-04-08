"""Extension onboarding: register strategies + rules without orchestrator edits."""

from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategy_registry import (
    CompressionStrategyRegistry,
)
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


class _ExtensionPrefixStrategy:
    __dynamic_config_runtime_tunable__ = False

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        # Orchestrator rejects size-increasing method outputs; shrink deterministically.
        if len(content) <= 8:
            return content
        return "EXT:" + content[8:]


def _shell_messages(*, output: str, command: str = "echo hi") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-ext",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-ext", content=output),
    ]


@pytest.mark.asyncio
async def test_extension_strategy_participates_via_registry_and_config_rule() -> None:
    registry = CompressionStrategyRegistry()
    registry.register_extension_strategy("ext_prefix", _ExtensionPrefixStrategy())
    service = ToolOutputCompressionService(strategy_registry=registry)

    base = DynamicCompressionConfig()
    methods = dict(base.methods)
    methods["ext_prefix"] = True
    rule = CompressionRule(
        name="extension_smoke",
        priority=1,
        when=CompressionRulePredicate(tool_name="shell"),
        pipeline=["ext_prefix"],
    )
    config = base.model_copy(
        update={
            "enabled": True,
            "min_bytes": 0,
            "methods": methods,
            "rules": [rule],
        }
    )

    original = "hello-extension-world" * 50
    messages = _shell_messages(output=original)
    result = await service.compress_messages(messages=messages, config=config)

    tool_out = result.messages[-1]
    assert tool_out.role == "tool"
    assert isinstance(tool_out.content, str)
    assert "EXT:" in tool_out.content
    assert result.records[-1].applied is True


@pytest.mark.asyncio
async def test_register_extension_strategy_is_idempotent_with_builtin_register() -> (
    None
):
    registry = CompressionStrategyRegistry()
    strategy = _ExtensionPrefixStrategy()
    registry.register_extension_strategy("ext_prefix", strategy)
    registry.register("ext_prefix", _ExtensionPrefixStrategy())
    assert registry.get("ext_prefix") is strategy
