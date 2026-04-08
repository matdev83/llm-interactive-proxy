from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionAlertsConfig,
    CompressionMarkerConfig,
    CompressionRecoveryConfig,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import (
    ToolOutputCompressionRecord,
    ToolOutputContext,
)
from src.core.services.compression_recovery_store import CompressionRecoveryStore
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _tool_messages(*, content: str, command: str = "git status") -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-observe",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-observe", content=content),
    ]


class _TrimStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        if len(content) <= 8:
            return content
        return content[: len(content) // 2]


class _FailStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        raise RuntimeError("intentional-compression-failure")


class _InflateStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        return content + " -- inflated --"


class _JsonSummaryStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level: object,
    ) -> str:
        del content, context, level
        return '{"summary":"compressed","items":1}'


class _FailingRecoveryStore(CompressionRecoveryStore):
    async def persist_if_eligible(
        self,
        *,
        original_content: str,
        record: ToolOutputCompressionRecord,
        config: CompressionRecoveryConfig,
    ) -> tuple[str | None, str | None]:
        return None, "Compression recovery artifact persistence failed open: OSError"


def _service_with_registry(
    registry: CompressionStrategyRegistry,
) -> ToolOutputCompressionService:
    return ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )


@pytest.mark.asyncio
async def test_telemetry_records_and_aggregate_rollups_include_required_fields() -> (
    None
):
    registry = CompressionStrategyRegistry()
    registry.register("trim", _TrimStrategy())
    service = _service_with_registry(registry)
    payload = "line\n" * 200
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"trim": True},
        rules=[
            CompressionRule(
                name="trim",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim"],
            )
        ],
    )

    result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=config,
    )

    record = result.records[0]
    assert record.applied is True
    assert record.original_bytes > record.compressed_bytes
    assert record.saved_bytes == record.original_bytes - record.compressed_bytes
    assert record.methods_applied == ["trim"]
    assert record.elapsed_total_ms >= 0
    assert record.original_sha256 is not None and len(record.original_sha256) == 64
    assert record.compressed_sha256 is not None and len(record.compressed_sha256) == 64
    assert record.correlation_id is not None
    assert "line" not in record.original_sha256

    metrics = result.aggregate_metrics
    assert metrics.processed_outputs == 1
    assert metrics.compressed_outputs == 1
    assert metrics.total_saved_bytes == record.saved_bytes
    assert metrics.by_method["trim"].applied == 1
    assert metrics.by_category["command_execution"] == 1
    assert metrics.by_level["conservative"] == 1


@pytest.mark.asyncio
async def test_alerts_emit_for_frequent_failures_and_are_rate_safe() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("boom", _FailStrategy())
    service = _service_with_registry(registry)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        alerts=CompressionAlertsConfig(
            enabled=True,
            failure_threshold=2,
            fallback_threshold=2,
            window_seconds=3600,
            cooldown_seconds=3600,
        ),
        methods={"boom": True},
        rules=[
            CompressionRule(
                name="boom",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["boom"],
            )
        ],
    )
    messages = _tool_messages(content="x" * 256)

    first = await service.compress_messages(messages=messages, config=config)
    second = await service.compress_messages(messages=messages, config=config)
    third = await service.compress_messages(messages=messages, config=config)
    fourth = await service.compress_messages(messages=messages, config=config)

    assert first.alerts == []
    assert len(second.alerts) == 1
    assert second.alerts[0].alert_type == "method_failure_rate"
    # Cooldown is active, so additional repeated failures do not re-emit immediately.
    assert third.alerts == []
    assert fourth.alerts == []


@pytest.mark.asyncio
async def test_alerts_emit_for_frequent_fallbacks() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("inflate", _InflateStrategy())
    service = _service_with_registry(registry)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        alerts=CompressionAlertsConfig(
            enabled=True,
            failure_threshold=10,
            fallback_threshold=2,
            window_seconds=3600,
            cooldown_seconds=3600,
        ),
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
    messages = _tool_messages(content="x" * 64)

    first = await service.compress_messages(messages=messages, config=config)
    second = await service.compress_messages(messages=messages, config=config)

    assert first.alerts == []
    assert len(second.alerts) == 1
    assert second.alerts[0].alert_type == "fallback_rate"


@pytest.mark.asyncio
async def test_effective_config_diagnostics_surfaces_active_inactive_and_ignored() -> (
    None
):
    registry = CompressionStrategyRegistry()
    registry.register("trim", _TrimStrategy())
    service = _service_with_registry(registry)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        categories={"command_execution": True, "search": False},
        methods={"trim": True, "line_dedupe": False},
        disable_categories=["unknown_category"],
        disable_methods=["unknown_method"],
        disable_tools=["shell"],
        rules=[
            CompressionRule(
                name="trim",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim"],
            )
        ],
    )

    result = await service.compress_messages(
        messages=_tool_messages(content="y" * 200),
        config=config,
    )

    diagnostics = result.effective_config
    assert diagnostics is not None
    assert "dynamic_compression.enabled" in diagnostics.active_controls
    assert "dynamic_compression.methods.line_dedupe" in diagnostics.inactive_controls
    assert any(
        control.endswith("unknown_method") for control in diagnostics.ignored_controls
    )
    assert diagnostics.reasons
    assert diagnostics.fingerprint


@pytest.mark.asyncio
async def test_recovery_handles_obey_thresholds_and_fail_open_on_store_errors(
    tmp_path: Path,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim", _TrimStrategy())
    base_config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"trim": True},
        rules=[
            CompressionRule(
                name="trim",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim"],
            )
        ],
        recovery=CompressionRecoveryConfig(
            mode="always",
            min_original_bytes=1,
            min_saved_bytes=1,
            storage_dir=str(tmp_path),
            max_artifacts=16,
            max_artifact_bytes=16_384,
            retention_seconds=600,
            hint_in_text=False,
        ),
    )
    payload = "z" * 512

    service = _service_with_registry(registry)
    result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=base_config,
    )
    record = result.records[0]
    assert record.recovery_handle is not None
    assert record.recovery_persisted is True
    assert (tmp_path / f"{record.recovery_handle}.json").exists()

    high_threshold_cfg = base_config.model_copy(
        update={
            "recovery": base_config.recovery.model_copy(
                update={"min_saved_bytes": 10_000}
            )
        }
    )
    no_handle_result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=high_threshold_cfg,
    )
    assert no_handle_result.records[0].recovery_handle is None

    failing_service = ToolOutputCompressionService(
        strategy_registry=registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
        recovery_store=_FailingRecoveryStore(),
    )
    fail_open_result = await failing_service.compress_messages(
        messages=_tool_messages(content=payload),
        config=base_config,
    )
    fail_open_record = fail_open_result.records[0]
    assert fail_open_record.applied is True
    assert fail_open_record.recovery_handle is None
    assert any(
        "failed open" in warning.lower() for warning in fail_open_record.warnings
    )


@pytest.mark.asyncio
async def test_fallback_recorded_when_size_increase_forces_skip() -> None:
    registry = CompressionStrategyRegistry()
    registry.register("inflate", _InflateStrategy())
    service = _service_with_registry(registry)
    config = DynamicCompressionConfig(
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

    result = await service.compress_messages(
        messages=_tool_messages(content="short-content"),
        config=config,
    )

    record = result.records[0]
    assert record.applied is False
    assert record.fallback_applied is True
    assert record.methods[0].skipped_reason == "size_increase"


@pytest.mark.asyncio
async def test_hash_and_correlation_reflect_final_content_after_recovery_hint(
    tmp_path: Path,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim", _TrimStrategy())
    service = _service_with_registry(registry)
    payload = "line\n" * 600
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        methods={"trim": True},
        rules=[
            CompressionRule(
                name="trim",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim"],
            )
        ],
        recovery=CompressionRecoveryConfig(
            mode="always",
            min_original_bytes=1,
            min_saved_bytes=1,
            storage_dir=str(tmp_path),
            max_artifacts=16,
            max_artifact_bytes=32_768,
            retention_seconds=600,
            hint_in_text=True,
        ),
    )

    result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=config,
    )

    record = result.records[0]
    final_content = str(result.messages[1].content)
    assert record.recovery_handle is not None
    assert record.recovery_hint_inserted is True
    assert "[RECOVERY_HANDLE:" in final_content

    expected_original_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    expected_compressed_sha = hashlib.sha256(final_content.encode("utf-8")).hexdigest()
    expected_correlation = hashlib.sha256(
        "|".join(
            [
                record.tool_call_id or "-",
                record.identity.tool_name,
                record.identity.command_signature or "-",
                expected_original_sha,
                expected_compressed_sha,
                str(record.saved_bytes),
            ]
        ).encode("utf-8")
    ).hexdigest()[:20]

    assert record.original_sha256 == expected_original_sha
    assert record.compressed_sha256 == expected_compressed_sha
    assert record.correlation_id == expected_correlation


@pytest.mark.asyncio
async def test_recovery_hint_is_skipped_when_it_would_exceed_original_size(
    tmp_path: Path,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("trim", _TrimStrategy())
    service = _service_with_registry(registry)
    payload = "abcdefghijklmnopqrstuvwxyz0123456789"
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        methods={"trim": True},
        rules=[
            CompressionRule(
                name="trim",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["trim"],
            )
        ],
        recovery=CompressionRecoveryConfig(
            mode="always",
            min_original_bytes=1,
            min_saved_bytes=1,
            storage_dir=str(tmp_path),
            max_artifacts=16,
            max_artifact_bytes=16_384,
            retention_seconds=600,
            hint_in_text=True,
        ),
    )

    result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=config,
    )

    record = result.records[0]
    final_content = str(result.messages[1].content)

    assert record.recovery_handle is not None
    assert record.recovery_hint_inserted is False
    assert "recovery_hint_skipped_size_increase" in record.warnings
    assert "[RECOVERY_HANDLE:" not in final_content
    assert len(final_content.encode("utf-8")) <= record.original_bytes


@pytest.mark.asyncio
async def test_recovery_handle_stays_out_of_band_for_structured_json_output(
    tmp_path: Path,
) -> None:
    registry = CompressionStrategyRegistry()
    registry.register("json_summary", _JsonSummaryStrategy())
    service = _service_with_registry(registry)
    payload = json.dumps(
        {
            "results": [
                {"name": "item", "value": "x" * 120, "status": "ok"} for _ in range(25)
            ]
        }
    )
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"json_summary": True},
        rules=[
            CompressionRule(
                name="json-summary",
                priority=1,
                when=CompressionRulePredicate(command_signature="git"),
                pipeline=["json_summary"],
            )
        ],
        recovery=CompressionRecoveryConfig(
            mode="always",
            min_original_bytes=1,
            min_saved_bytes=1,
            storage_dir=str(tmp_path),
            max_artifacts=16,
            max_artifact_bytes=32_768,
            retention_seconds=600,
            hint_in_text=True,
        ),
    )

    result = await service.compress_messages(
        messages=_tool_messages(content=payload),
        config=config,
    )

    record = result.records[0]
    final_content = str(result.messages[1].content)

    assert record.recovery_handle is not None
    assert record.recovery_hint_inserted is False
    assert "[RECOVERY_HANDLE:" not in final_content
    parsed = json.loads(final_content)
    assert isinstance(parsed, dict)
