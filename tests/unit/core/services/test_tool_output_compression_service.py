from __future__ import annotations

import logging
from re import Pattern

import pytest
import src.core.services.tool_output_compression_service as compression_service_module
from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers._compression_registration import (
    register_tool_output_compression_services,
)
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionLevel,
    CompressionMarkerConfig,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
    MarkerStyle,
    OutputPatternRuleConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategies import (
    FileDetailLevelsStrategy,
    LineDedupeStrategy,
    OutputPatternMatchStrategy,
)
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _build_tool_messages(command: str, output: str) -> list[ChatMessage]:
    return _build_messages_for_tool(
        tool_name="shell",
        arguments=f'{{"command":"{command}"}}',
        output=output,
    )


def _build_messages_for_tool(
    *,
    tool_name: str,
    arguments: str,
    output: str,
) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name=tool_name,
                        arguments=arguments,
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=output),
    ]


def _build_service_with_default_registry() -> ToolOutputCompressionService:
    services = ServiceCollection()
    register_tool_output_compression_services(
        services=services,
        logger=logging.getLogger(__name__),
    )
    provider = services.build_service_provider(run_post_build_hooks=False)
    return provider.get_required_service(ToolOutputCompressionService)


class _SuffixStrategy:
    def __init__(self, suffix: str, *, fail: bool = False) -> None:
        self._suffix = suffix
        self._fail = fail

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if self._fail:
            raise RuntimeError("boom")
        if len(content) <= 1:
            return content
        trim_size = min(len(self._suffix), len(content) - 1)
        return f"{content[:-trim_size]}{self._suffix}"


class _LevelAwareStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if level == CompressionLevel.CONSERVATIVE:
            return content[:160]
        if level == CompressionLevel.BALANCED:
            return content[:120]
        return content[:60]


class _NonMonotonicLevelStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if level == CompressionLevel.CONSERVATIVE:
            return content[:170]
        if level == CompressionLevel.BALANCED:
            return content[:90]
        return content[:140]


class _AggressiveFailAfterBalancedStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if level == CompressionLevel.CONSERVATIVE:
            return content[:170]
        if level == CompressionLevel.BALANCED:
            return content[:110]
        raise RuntimeError("aggressive failure")


class _TrimOneStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if len(content) <= 1:
            return content
        return content[:-1]


class _HalfTrimStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        if len(content) <= 2:
            return content
        return content[: len(content) // 2]


class _TokenReplaceStrategy:
    def __init__(self, old: str, new: str) -> None:
        self._old = old
        self._new = new

    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: CompressionLevel,
    ) -> str:
        return content.replace(self._old, self._new)


class _CaptureLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[str, dict[str, object]]] = []
        self.debug_calls: list[tuple[str, dict[str, object]]] = []

    def is_enabled_for(self, level: int) -> bool:
        return True

    def info(self, event: str, **kwargs: object) -> None:
        self.info_calls.append((event, kwargs))

    def debug(self, event: str, **kwargs: object) -> None:
        self.debug_calls.append((event, kwargs))


def test_identity_resolver_detects_command_and_explicit_format_flags() -> None:
    messages = _build_tool_messages(
        "git diff --stat --color=never",
        "diff --git a/a.py b/a.py\n@@ -1,1 +1,2 @@\n+line",
    )
    resolver = ToolIdentityResolver()

    context = resolver.resolve_tool_output(messages=messages, tool_message=messages[1])

    assert context is not None
    assert context.identity.tool_name == "shell"
    assert context.identity.command_signature == "git"
    assert context.identity.command_prefix == "git diff"
    assert "--stat" in context.identity.explicit_format_flags
    assert context.has_diff_markers is True
    assert context.has_explicit_format is True


def test_selector_uses_priority_then_declaration_order() -> None:
    resolver = ToolIdentityResolver()
    selector = RuleBasedStrategySelector()
    messages = _build_tool_messages("git status", "M src/app.py")
    context = resolver.resolve_tool_output(messages=messages, tool_message=messages[1])
    assert context is not None

    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        rules=[
            CompressionRule(
                name="first",
                priority=10,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["first_method"],
            ),
            CompressionRule(
                name="second",
                priority=10,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["second_method"],
            ),
        ],
    )

    selected = selector.select_rule(context, cfg)
    assert selected is not None
    assert selected.name == "first"


@pytest.mark.asyncio
async def test_service_fail_open_returns_last_successful_on_pipeline_error() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("ok", _SuffixStrategy("-ok"))
    registry.register("boom", _SuffixStrategy("-boom", fail=True))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"ok": True, "boom": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["ok", "boom"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    tool_msg = result.messages[1]
    assert tool_msg.content == "he-ok"
    assert result.records[0].failed_open is True


@pytest.mark.asyncio
async def test_service_rolls_back_when_method_increases_size() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("inflate", _SuffixStrategy("-this-is-bigger-than-input"))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "tiny")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        methods={"inflate": True},
        rules=[
            CompressionRule(
                name="inflate",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["inflate"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    assert result.messages[1].content == "tiny"
    assert result.records[0].compressed_bytes == result.records[0].original_bytes


@pytest.mark.asyncio
async def test_service_skips_small_outputs_and_disabled_categories() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("ok", _SuffixStrategy("-ok"))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "small")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=1024,
        methods={"ok": True},
        disable_categories=["command_execution"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["ok"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    assert result.messages[1].content == "small"
    assert result.records[0].applied is False


@pytest.mark.asyncio
async def test_service_skips_compaction_stub_outputs_already_processed() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    compacted_payload = (
        "[COMPACTED] Previous output for foo.py (2048 bytes) was removed "
        "because a newer result exists."
    )
    messages = _build_tool_messages("git status", compacted_payload)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == compacted_payload
    assert result.records[0].applied is False
    assert "skipped_already_processed_compaction" in result.records[0].warnings


@pytest.mark.asyncio
async def test_service_skips_outputs_marked_compacted_in_metadata() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "x" * 200)
    messages[1] = messages[1].model_copy(update={"metadata": {"_compacted": True}})
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == "x" * 200
    assert result.records[0].applied is False
    assert "skipped_already_processed_compaction" in result.records[0].warnings


@pytest.mark.asyncio
async def test_service_sets_compacted_metadata_on_first_compression() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "x" * 200)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    first = await service.compress_messages(messages=messages, config=cfg)

    assert first.records[0].applied is True
    assert first.messages[1].metadata == {"_compacted": True}

    second = await service.compress_messages(messages=first.messages, config=cfg)

    assert second.records[0].applied is False
    assert "skipped_already_processed_compaction" in second.records[0].warnings


@pytest.mark.asyncio
async def test_service_skips_outputs_with_compressed_marker_already_processed() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    previously_compressed = (
        "[COMPRESSED level=balanced methods=ansi_normalize,diff_compact saved=2048B]\n"
        "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n"
    )
    messages = _build_tool_messages("git diff", previously_compressed)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == previously_compressed
    assert result.records[0].applied is False
    assert "skipped_already_processed_compression" in result.records[0].warnings


@pytest.mark.asyncio
async def test_service_skips_outputs_with_compressed_suffix_marker_already_processed() -> (
    None
):
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    previously_compressed = (
        "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n"
        "[COMPRESSED level=balanced methods=ansi_normalize,diff_compact saved=2048B]"
    )
    messages = _build_tool_messages("git diff", previously_compressed)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == previously_compressed
    assert result.records[0].applied is False
    assert "skipped_already_processed_compression" in result.records[0].warnings


@pytest.mark.asyncio
async def test_service_skips_output_with_suffix_marker_on_second_pass() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    original_content = "line-1\nline-2\nline-3\nline-4\nline-5\n"
    messages = _build_tool_messages("git diff", original_content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(
            enabled=True,
            style=MarkerStyle.SUFFIX,
            include_sizes=False,
            include_methods=False,
        ),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["half_trim"],
            )
        ],
    )

    first_pass = await service.compress_messages(messages=messages, config=cfg)
    assert first_pass.records[0].applied is True
    first_content = first_pass.messages[1].content

    second_pass = await service.compress_messages(
        messages=first_pass.messages, config=cfg
    )
    assert second_pass.records[0].applied is False
    assert second_pass.messages[1].content == first_content


@pytest.mark.asyncio
async def test_service_skips_artifact_preview_system_reminder_outputs() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    artifact_preview = (
        "<system-reminder> Extracted artifact from /tmp/demo.log. "
        "Showing first 200 lines.</system-reminder>\n"
        "line-1\nline-2\nline-3\nline-4\nline-5\nline-6\n"
    )
    messages = _build_tool_messages("cat /tmp/demo.log", artifact_preview)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == artifact_preview
    assert result.records[0].applied is False
    assert "skipped_already_processed_artifact_preview" in result.records[0].warnings


@pytest.mark.asyncio
async def test_pytest_failure_focus_runtime_override_uses_explicit_min_lines_field() -> (
    None
):
    service = _build_service_with_default_registry()
    payload = "\n".join(
        [
            "============================= test session starts =============================",
            "collected 2 items",
            "tests/test_demo.py::test_one PASSED 0.01s call",
            "tests/test_demo.py::test_two PASSED 0.02s call",
            "============================== 2 passed in 0.03s ==============================",
            "",
        ]
    )
    messages = _build_tool_messages("pytest -q", payload)
    base_config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"pytest_failure_focus": True},
        rules=[
            CompressionRule(
                name="pytest-focus",
                priority=1,
                when=CompressionRulePredicate(command_signature="pytest"),
                pipeline=["pytest_failure_focus"],
            )
        ],
    )

    compressed = await service.compress_messages(
        messages=messages,
        config=base_config.model_copy(update={"pytest_failure_focus_min_lines": 0}),
    )
    bypassed = await service.compress_messages(
        messages=messages,
        config=base_config.model_copy(update={"pytest_failure_focus_min_lines": 10}),
    )

    assert compressed.messages[1].content != payload
    assert compressed.records[0].applied is True
    assert bypassed.messages[1].content == payload
    assert bypassed.records[0].applied is False


@pytest.mark.asyncio
async def test_marker_policy_inserts_for_text_and_suppresses_for_json() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    text_messages = _build_tool_messages("git status", "hello world\n" * 20)
    json_messages = _build_tool_messages("cat data.json", '{"a": 1, "b": 2}')

    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(include_sizes=False, include_methods=False),
        methods={"half_trim": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(),
                pipeline=["half_trim"],
            )
        ],
    )

    text_result = await service.compress_messages(messages=text_messages, config=cfg)
    json_result = await service.compress_messages(messages=json_messages, config=cfg)

    assert str(text_result.messages[1].content).startswith("[COMPRESSED")
    assert "[COMPRESSED" not in str(json_result.messages[1].content)
    assert text_result.records[0].marker_inserted is True
    assert json_result.records[0].marker_inserted is False


@pytest.mark.asyncio
async def test_marker_insertion_rolls_back_when_it_would_increase_size() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim_one", _TrimOneStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "abcdefghij")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        methods={"trim_one": True},
        rules=[
            CompressionRule(
                name="trim-one",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim_one"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == "abcdefghi"
    assert result.records[0].marker_inserted is False
    assert "marker_rolled_back_size_increase" in result.records[0].warnings


@pytest.mark.asyncio
async def test_budget_pressure_escalation_respects_max_level() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("level_aware", _LevelAwareStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    payload = "x" * 200  # ~50 estimated tokens
    messages = _build_tool_messages("git status", payload)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.CONSERVATIVE,
        max_level=CompressionLevel.AGGRESSIVE,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"level_aware": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["level_aware"],
            )
        ],
    )

    result = await service.compress_messages(
        messages=messages,
        config=cfg,
        target_token_budget=20,
    )

    assert result.records[0].final_level == CompressionLevel.AGGRESSIVE
    assert len(str(result.messages[1].content)) <= 80


@pytest.mark.asyncio
async def test_budget_escalation_prefers_best_candidate_when_aggressive_degrades() -> (
    None
):
    registry = CompressionStrategyRegistry()
    registry.register("non_monotonic", _NonMonotonicLevelStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    payload = "x" * 240
    messages = _build_tool_messages("git status", payload)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.CONSERVATIVE,
        max_level=CompressionLevel.AGGRESSIVE,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"non_monotonic": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["non_monotonic"],
            )
        ],
    )

    result = await service.compress_messages(
        messages=messages,
        config=cfg,
        target_token_budget=10,
    )

    assert result.records[0].final_level == CompressionLevel.BALANCED
    assert len(str(result.messages[1].content)) == 90
    assert result.records[0].failed_open is False


@pytest.mark.asyncio
async def test_budget_escalation_preserves_successful_candidate_on_fail_open() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("fail_aggressive", _AggressiveFailAfterBalancedStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    payload = "x" * 240
    messages = _build_tool_messages("git status", payload)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.CONSERVATIVE,
        max_level=CompressionLevel.AGGRESSIVE,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"fail_aggressive": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["fail_aggressive"],
            )
        ],
    )

    result = await service.compress_messages(
        messages=messages,
        config=cfg,
        target_token_budget=20,
    )

    record = result.records[0]
    assert record.final_level == CompressionLevel.BALANCED
    assert len(str(result.messages[1].content)) == 110
    assert record.failed_open is True
    assert record.failure_reason == "pipeline_fail_open"
    assert all(method.error is None for method in record.methods)


@pytest.mark.asyncio
async def test_pipeline_order_sensitive_strategy_follows_declared_pipeline_order() -> (
    None
):
    registry = CompressionStrategyRegistry()
    registry.register("stage_one", _TokenReplaceStrategy("alpha", "A"))
    registry.register("stage_two", _TokenReplaceStrategy("A-beta", "AB"))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("git status", "alpha-beta")

    ordered_cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"stage_one": True, "stage_two": True},
        rules=[
            CompressionRule(
                name="ordered",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["stage_one", "stage_two"],
            )
        ],
    )
    reversed_cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"stage_one": True, "stage_two": True},
        rules=[
            CompressionRule(
                name="reversed",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["stage_two", "stage_one"],
            )
        ],
    )

    ordered_result = await service.compress_messages(
        messages=messages, config=ordered_cfg
    )
    reversed_result = await service.compress_messages(
        messages=messages, config=reversed_cfg
    )

    assert ordered_result.messages[1].content == "AB"
    assert reversed_result.messages[1].content == "A-beta"
    assert ordered_result.messages[1].content != reversed_result.messages[1].content


@pytest.mark.asyncio
async def test_service_logs_debug_for_evaluated_non_applied_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("inflate", _SuffixStrategy("-this-is-bigger-than-input"))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "tiny")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"inflate": True},
        rules=[
            CompressionRule(
                name="inflate",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["inflate"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is False
    assert result.records[0].failed_open is False
    # Suppressed to reduce log noise: not_applied is now in _NOISY_NOOP_DECISION_REASONS
    assert len(capture_logger.info_calls) == 0
    assert len(capture_logger.debug_calls) == 0


@pytest.mark.asyncio
async def test_service_logs_info_for_fail_open_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("boom", _SuffixStrategy("-boom", fail=True))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"boom": True},
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["boom"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].failed_open is True
    assert result.records[0].applied is False
    assert len(capture_logger.info_calls) == 1
    assert len(capture_logger.debug_calls) == 0
    _, metadata = capture_logger.info_calls[0]
    assert metadata["decision_reason"] == "failed_open"
    assert metadata["methods_attempted"] == ["boom"]
    assert metadata["methods_applied"] == []
    assert metadata["failed_open"] is True
    assert metadata["applied"] is False
    assert metadata["tool_name"] == "shell"
    assert metadata["tool_category"] == "command_execution"
    assert metadata["bytes_in"] == 5
    assert metadata["bytes_out"] == 5
    assert "content" not in metadata


@pytest.mark.asyncio
async def test_service_logs_applied_outcome_as_debug_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim_one", _TrimOneStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"trim_one": True},
        rules=[
            CompressionRule(
                name="trim-default",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim_one"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is True
    assert len(capture_logger.info_calls) == 0
    assert len(capture_logger.debug_calls) == 1
    _, metadata = capture_logger.debug_calls[0]
    assert metadata["decision_reason"] == "applied"


@pytest.mark.asyncio
async def test_service_logs_applied_outcome_as_info_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim_one", _TrimOneStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        per_output_evaluation_log_level="info",
        methods={"trim_one": True},
        rules=[
            CompressionRule(
                name="trim-info",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim_one"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is True
    assert len(capture_logger.info_calls) == 1
    assert len(capture_logger.debug_calls) == 0
    _, metadata = capture_logger.info_calls[0]
    assert metadata["decision_reason"] == "applied"


@pytest.mark.asyncio
async def test_service_suppresses_applied_outcome_logs_when_configured_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim_one", _TrimOneStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        per_output_evaluation_log_level="off",
        methods={"trim_one": True},
        rules=[
            CompressionRule(
                name="trim-off",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim_one"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is True
    assert len(capture_logger.info_calls) == 0
    assert len(capture_logger.debug_calls) == 0


@pytest.mark.asyncio
async def test_service_logs_applied_outcome_only_once_for_same_compression_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim_one", _TrimOneStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("git status", "hello")
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        per_output_evaluation_log_level="info",
        methods={"trim_one": True},
        rules=[
            CompressionRule(
                name="trim-once",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim_one"],
            )
        ],
    )

    first_result = await service.compress_messages(messages=messages, config=cfg)
    second_result = await service.compress_messages(messages=messages, config=cfg)

    assert first_result.records[0].applied is True
    assert second_result.records[0].applied is True
    assert len(capture_logger.info_calls) == 1
    _, metadata = capture_logger.info_calls[0]
    assert metadata["decision_reason"] == "applied"


@pytest.mark.asyncio
async def test_service_logs_applied_outcome_again_when_compressed_payload_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("replace", _TokenReplaceStrategy("beta", "b"))
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        per_output_evaluation_log_level="info",
        methods={"replace": True},
        rules=[
            CompressionRule(
                name="replace-dynamic",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["replace"],
            )
        ],
    )

    first_result = await service.compress_messages(
        messages=_build_tool_messages("git status", "alpha beta"),
        config=cfg,
    )
    second_result = await service.compress_messages(
        messages=_build_tool_messages("git status", "alpha beta beta"),
        config=cfg,
    )

    assert (
        first_result.records[0].compressed_sha256
        != second_result.records[0].compressed_sha256
    )
    assert len(capture_logger.info_calls) == 2


@pytest.mark.asyncio
async def test_service_suppresses_debug_for_compression_disabled_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _build_service_with_default_registry()
    capture_logger = _CaptureLogger()
    monkeypatch.setattr(compression_service_module, "logger", capture_logger)
    messages = _build_tool_messages("python script.py", "stdout line")
    cfg = DynamicCompressionConfig(enabled=False)

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is False
    assert result.records[0].failed_open is False
    assert len(capture_logger.info_calls) == 0
    assert len(capture_logger.debug_calls) == 0


def test_selector_no_match_returns_none() -> None:
    selector = RuleBasedStrategySelector()
    cfg = DynamicCompressionConfig(
        enabled=True,
        rules=[
            CompressionRule(
                name="only_search",
                priority=1,
                when=CompressionRulePredicate(tool_category="search"),
                pipeline=["noop"],
            )
        ],
    )
    context = ToolOutputContext.for_text(
        tool_name="shell",
        tool_category="command_execution",
        content="echo ok",
    )

    assert selector.select_rule(context, cfg) is None


@pytest.mark.asyncio
async def test_file_workflow_prefers_known_strategy_and_falls_back_to_generic() -> None:
    registry = CompressionStrategyRegistry()
    registry.register(
        "file_detail_levels",
        FileDetailLevelsStrategy(detail_mode="signatures"),
    )
    registry.register("line_dedupe", LineDedupeStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"file_detail_levels": True, "line_dedupe": True},
        rules=[
            CompressionRule(
                name="file-workflow",
                priority=1,
                when=CompressionRulePredicate(tool_name="shell"),
                pipeline=["file_detail_levels", "line_dedupe"],
            )
        ],
    )

    known_payload = (
        "def alpha():\n"
        + "".join(f"    alpha_value_{idx} = {idx}\n" for idx in range(40))
        + "    return 1\n\n"
        + "def beta():\n"
        + "".join(f"    beta_value_{idx} = {idx}\n" for idx in range(40))
        + "    return 2\n"
    )
    known_messages = _build_tool_messages("cat src/example.py", known_payload)
    unknown_messages = _build_tool_messages(
        "custom_reader src/example.py",
        "repeat\nrepeat\nrepeat\n",
    )

    known_result = await service.compress_messages(messages=known_messages, config=cfg)
    unknown_result = await service.compress_messages(
        messages=unknown_messages, config=cfg
    )

    known_output = str(known_result.messages[1].content)
    unknown_output = str(unknown_result.messages[1].content)
    assert "def alpha():" in known_output
    assert "lines omitted" in known_output
    assert unknown_output == "repeat (x3)\n"


@pytest.mark.asyncio
async def test_service_uses_effective_runtime_output_pattern_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_search(
        _self: object, pattern: Pattern[str], text: str
    ) -> tuple[bool, bool]:
        return (pattern.search(text) is not None, False)

    monkeypatch.setattr(
        OutputPatternMatchStrategy,
        "_search_with_timeout",
        _fake_search,
    )
    service = _build_service_with_default_registry()
    messages = _build_tool_messages(
        "pytest -q", "Build succeeded in 2.0s with 0 errors"
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"output_pattern_match": True},
        output_pattern_regex_timeout_ms=500,
        output_pattern_rules=[
            OutputPatternRuleConfig(
                pattern=r"(?is)build succeeded.*0 errors",
                message="build: ok",
                fallback_message="build: ok",
            )
        ],
        rules=[
            CompressionRule(
                name="pattern",
                priority=1,
                when=CompressionRulePredicate(command_signature="pytest"),
                pipeline=["output_pattern_match"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == "build: ok"


@pytest.mark.asyncio
async def test_service_uses_effective_runtime_diff_limits() -> None:
    service = _build_service_with_default_registry()
    diff_lines = [
        "diff --git a/src/main.py b/src/main.py",
        "--- a/src/main.py",
        "+++ b/src/main.py",
        "@@ -1,2 +1,50 @@ def build():",
    ]
    diff_lines.extend([f"+added line {idx}" for idx in range(50)])
    diff_lines.append("diff --git a/src/util.py b/src/util.py")
    diff_lines.append("--- a/src/util.py")
    diff_lines.append("+++ b/src/util.py")
    diff_lines.append("@@ -1,3 +1,40 @@")
    diff_lines.extend([f"+util line {idx}" for idx in range(40)])
    messages = _build_tool_messages("git diff", "\n".join(diff_lines))
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.BALANCED,
        max_level=CompressionLevel.BALANCED,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"diff_compact": True},
        diff_max_lines_per_hunk=2,
        diff_max_total_lines=200,
        rules=[
            CompressionRule(
                name="diff",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["diff_compact"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "lines skipped" in compressed


@pytest.mark.asyncio
async def test_service_uses_effective_runtime_search_grouping_limits() -> None:
    service = _build_service_with_default_registry()
    search_output = "".join(
        f"src/a.py:{10 + idx}:def target_{idx}()\n" for idx in range(8)
    )
    messages = _build_tool_messages("rg target src", search_output)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.BALANCED,
        max_level=CompressionLevel.BALANCED,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"search_results_grouping": True},
        search_max_matches_per_file=1,
        search_context_lines=0,
        rules=[
            CompressionRule(
                name="search",
                priority=1,
                when=CompressionRulePredicate(command_signature="rg"),
                pipeline=["search_results_grouping"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "10: def target_0()" in compressed
    assert "11: def target_1()" not in compressed
    assert "+7 matches truncated" in compressed


@pytest.mark.asyncio
async def test_service_uses_effective_runtime_directory_noise_filters() -> None:
    service = _build_service_with_default_registry()
    listing = (
        "custom_noise/cache/a.bin\n"
        "custom_noise/cache/b.bin\n"
        "node_modules/pkg/index.js\n"
        "node_modules/pkg/lib/util.js\n"
        "src/app/main.py\n"
        "src/app/utils.py\n"
    )
    messages = _build_tool_messages("ls -la", listing)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.BALANCED,
        max_level=CompressionLevel.BALANCED,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"directory_tree_summary": True},
        noise_directories=["custom_noise"],
        rules=[
            CompressionRule(
                name="ls",
                priority=1,
                when=CompressionRulePredicate(command_signature="ls"),
                pipeline=["directory_tree_summary"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "custom_noise/" not in compressed
    assert "node_modules/" in compressed


@pytest.mark.asyncio
async def test_service_uses_effective_runtime_file_detail_line_numbers() -> None:
    service = _build_service_with_default_registry()
    file_content = (
        "def alpha(x):\n"
        + "".join(f"    alpha_value_{idx} = {idx}\n" for idx in range(30))
        + "    return x\n\n"
        + "class Demo:\n"
        + "".join(f"    demo_value_{idx} = {idx}\n" for idx in range(30))
        + "    pass\n"
    )
    messages = _build_tool_messages("cat src/example.py", file_content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        level=CompressionLevel.AGGRESSIVE,
        max_level=CompressionLevel.AGGRESSIVE,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"file_detail_levels": True},
        file_detail_mode="signatures",
        file_detail_include_line_numbers=True,
        rules=[
            CompressionRule(
                name="file-read",
                priority=1,
                when=CompressionRulePredicate(command_signature="cat"),
                pipeline=["file_detail_levels"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "1: def alpha(x):" in compressed
    assert "34: class Demo:" in compressed
    assert "lines omitted" in compressed


@pytest.mark.asyncio
async def test_default_rules_apply_generic_fallback_for_unknown_command() -> None:
    service = _build_service_with_default_registry()
    content = ("repeat warning line\n" * 160) + "done\n"
    messages = _build_tool_messages("customcli run report", content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert compressed != content
    assert result.records[0].applied is True
    assert "line_dedupe" in result.records[0].methods_applied


@pytest.mark.asyncio
async def test_default_rules_apply_category_search_grouping_for_non_shell_tools() -> (
    None
):
    service = _build_service_with_default_registry()
    search_output = "".join(
        f"src/a.py:{10 + idx}:def target_{idx}()\n" for idx in range(40)
    )
    messages = _build_messages_for_tool(
        tool_name="search",
        arguments='{"query":"target","path":"src"}',
        output=search_output,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "[file] src/a.py" in compressed
    assert "10: def target_0()" in compressed
    assert result.records[0].applied is True
    assert any(
        method.name == "search_results_grouping" for method in result.records[0].methods
    )


@pytest.mark.asyncio
async def test_default_rules_apply_category_file_read_details_for_non_shell_tools() -> (
    None
):
    service = _build_service_with_default_registry()
    file_content = (
        "def alpha(x):\n"
        + "".join(f"    alpha_value_{idx} = {idx}\n" for idx in range(60))
        + "    return x\n\n"
        + "class Demo:\n"
        + "".join(f"    demo_value_{idx} = {idx}\n" for idx in range(60))
        + "    pass\n"
    )
    messages = _build_messages_for_tool(
        tool_name="read_file",
        arguments='{"path":"src/example.py"}',
        output=file_content,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        disable_tools=[],
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "def alpha(x):" in compressed
    assert "lines omitted" in compressed
    assert result.records[0].applied is True
    assert any(
        method.name == "file_detail_levels" for method in result.records[0].methods
    )


@pytest.mark.asyncio
async def test_default_rules_route_git_status_through_structured_pipeline() -> None:
    service = _build_service_with_default_registry()
    lines = ["## develop...origin/develop"]
    lines += [f" M services/long_name_module_{i:02d}.py" for i in range(20)]
    content = "\n".join(lines) + "\n"
    messages = _build_tool_messages("git status", content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    compressed = str(result.messages[1].content)

    assert "develop" in compressed
    assert "unstaged:" in compressed
    assert "services/long_name_module_00.py" in compressed


@pytest.mark.asyncio
async def test_default_rules_route_git_commit_through_mutating_ack() -> None:
    service = _build_service_with_default_registry()
    content = (
        "[main deadbeef1234567890] Fix things\n"
        " 2 files changed, 4 insertions(+), 1 deletion(-)\n"
        + "remote: Resolving deltas: 100%\n" * 40
    )
    messages = _build_tool_messages("git commit", content)
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)
    out = str(result.messages[1].content)

    assert "deadbeef1234567890" in out
    assert "branch=main" in out


@pytest.mark.asyncio
async def test_git_diff_stat_explicit_format_is_not_matched_by_default_rules() -> None:
    service = _build_service_with_default_registry()
    stat_out = (
        " example.py | 10 +++++++++-\n" * 25
    ) + " 1 file changed, 5 insertions(+)\n"
    messages = _build_tool_messages(
        "git diff --stat --color=never",
        stat_out,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=DynamicCompressionConfig().rules,
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.messages[1].content == stat_out


@pytest.mark.asyncio
async def test_service_skips_tool_matching_tool_name_substring() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages_for_tool(
        tool_name="fff_grep",
        arguments='{"pattern":"target","path":"src"}',
        output="src/a.py:10:def target()\n" * 100,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        disable_tool_name_substrings=["fff"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(tool_category="search"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is False
    assert result.messages[1].content == messages[1].content
    assert result.records[0].methods == []


@pytest.mark.asyncio
async def test_service_skips_tool_matching_substring_anywhere_in_name() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages_for_tool(
        tool_name="turbo_fff_grep",
        arguments='{"pattern":"target","path":"src"}',
        output="src/a.py:10:def target()\n" * 100,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        disable_tool_name_substrings=["fff"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(tool_category="search"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is False
    assert result.messages[1].content == messages[1].content
    assert result.records[0].methods == []


@pytest.mark.asyncio
async def test_service_does_not_skip_tool_not_matching_substring() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages_for_tool(
        tool_name="grep_tool",
        arguments='{"pattern":"target","path":"src"}',
        output="src/a.py:10:def target()\n" * 100,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        disable_tool_name_substrings=["fff"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is True
    assert result.messages[1].content != messages[1].content


@pytest.mark.asyncio
async def test_tool_name_substring_is_case_insensitive() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages_for_tool(
        tool_name="FFF_FIND_FILES",
        arguments='{"path":"src"}',
        output="src/a.py\nsrc/b.py\n" * 100,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        disable_tool_name_substrings=["fff"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(tool_category="list_dir"),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.records[0].applied is False
    assert result.messages[1].content == messages[1].content
    assert result.records[0].methods == []


@pytest.mark.asyncio
async def test_tool_name_substring_appears_in_effective_config_diagnostics() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("half_trim", _HalfTrimStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_messages_for_tool(
        tool_name="grep_tool",
        arguments='{"pattern":"target","path":"src"}',
        output="src/a.py:10:def target()\n" * 100,
    )
    cfg = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"half_trim": True},
        disable_tool_name_substrings=["fff"],
        rules=[
            CompressionRule(
                name="default",
                priority=1,
                when=CompressionRulePredicate(),
                pipeline=["half_trim"],
            )
        ],
    )

    result = await service.compress_messages(messages=messages, config=cfg)

    assert result.effective_config is not None
    assert (
        "dynamic_compression.disable_tool_name_substrings.fff"
        in result.effective_config.active_controls
    )
