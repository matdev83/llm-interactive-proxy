from __future__ import annotations

import json
import logging

import pytest
from src.core.di.container import ServiceCollection
from src.core.di.registration_helpers._compression_registration import (
    register_tool_output_compression_services,
)
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionMarkerConfig,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.declarative_compression_rules import (
    DeclarativeFilterPipeline,
    DeclarativeRuleRegistry,
)
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _build_tool_messages(command: str, output: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="tc-1",
                    function=FunctionCall(
                        name="shell",
                        arguments=f'{{"command":"{command}"}}',
                    ),
                )
            ],
        ),
        ChatMessage(role="tool", tool_call_id="tc-1", content=output),
    ]


def _context_for(command: str, content: str) -> ToolOutputContext:
    messages = _build_tool_messages(command, content)
    resolver = ToolIdentityResolver()
    context = resolver.resolve_tool_output(messages=messages, tool_message=messages[1])
    assert context is not None
    return context


def _build_service_with_default_registry() -> ToolOutputCompressionService:
    services = ServiceCollection()
    register_tool_output_compression_services(
        services=services,
        logger=logging.getLogger(__name__),
    )
    provider = services.build_service_provider(run_post_build_hooks=False)
    return provider.get_required_service(ToolOutputCompressionService)


class _CodeWinsStrategy:
    def compress(
        self,
        content: str,
        *,
        context: ToolOutputContext,
        level,
    ) -> str:
        return "code:ok"


def test_declarative_registry_loads_builtins_and_skips_invalid_rules() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "invalid_regex_rule",
                "match_command": "[",
                "max_lines": 20,
            },
            {
                "name": "valid_custom_rule",
                "match_command": r"^customtool\b",
                "strip_ansi": True,
                "max_lines": 20,
                "on_empty": "customtool: ok",
            },
        ]
    )

    resolved = registry.resolve(config)

    assert len(resolved.rules) >= 50
    assert any(rule.name == "valid_custom_rule" for rule in resolved.rules)
    assert not any(rule.name == "invalid_regex_rule" for rule in resolved.rules)
    assert any(
        "invalid match_command regex" in warning.lower()
        for warning in resolved.warnings
    )


def test_declarative_registry_warns_on_unknown_stage_key() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "unknown_stage_key_rule",
                "match_command": r"^mystery\b",
                "strip_lines": [r"^ignore$"],
                "strip_linez": [r"^typo$"],
            }
        ]
    )

    resolved = registry.resolve(config)

    assert any(rule.name == "unknown_stage_key_rule" for rule in resolved.rules)
    assert any(
        "ignored unknown key 'strip_linez'" in warning.lower()
        for warning in resolved.warnings
    )


def test_declarative_registry_loads_declarative_rule_files_path(
    tmp_path, monkeypatch
) -> None:
    rule_file = tmp_path / "declarative_rules.json"
    rule_file.write_text(
        json.dumps(
            {
                "declarative_rules": [
                    {
                        "name": "file_loaded_rule",
                        "match_command": r"^fromfile\b",
                        "match_output": [
                            {"pattern": r"BUILD SUCCESSFUL", "message": "file: ok"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(declarative_rule_files=["declarative_rules.json"])

    resolved = registry.resolve(config)
    loaded_rule = next(
        rule for rule in resolved.rules if rule.name == "file_loaded_rule"
    )
    transformed = registry.apply_rule(
        rule=loaded_rule, content="BUILD SUCCESSFUL in 2s\n"
    )

    assert transformed == "file: ok"
    assert not any("file not found" in warning.lower() for warning in resolved.warnings)


def test_declarative_pipeline_applies_all_8_stages_in_order() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "pipeline_order",
                "match_command": r"^customtool\b",
                "strip_ansi": True,
                "replace": [{"pattern": "foo", "replacement": "bar"}],
                "match_output": [{"pattern": "NO_MATCH", "message": "short-circuit"}],
                "strip_lines": [r"^drop"],
                "truncate_lines_at": 8,
                "head_lines": 2,
                "tail_lines": 1,
                "max_lines": 4,
                "on_empty": "customtool: ok",
            }
        ]
    )
    resolved = registry.resolve(config)
    target_rule = next(rule for rule in resolved.rules if rule.name == "pipeline_order")

    content = (
        "\x1b[31mfoo123456789\x1b[0m\n"
        "keep me\n"
        "keep me too\n"
        "drop this line\n"
        "final line\n"
    )
    transformed = registry.apply_rule(rule=target_rule, content=content)

    assert transformed == (
        "bar12...\n" "keep me\n" "... (1 lines omitted)\n" "final...\n"
    )


def test_declarative_pipeline_match_output_unless_and_on_empty_fallback() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "guarded_match_output",
                "match_command": r"^gradle\b",
                "match_output": [
                    {
                        "pattern": r"BUILD SUCCESSFUL",
                        "message": "gradle: ok",
                        "unless": r"FAILED|error:",
                    }
                ],
            },
            {
                "name": "empty_fallback",
                "match_command": r"^emptier\b",
                "strip_lines": [r"^.*$"],
                "on_empty": "emptier: ok",
            },
        ]
    )
    resolved = registry.resolve(config)
    by_name = {rule.name: rule for rule in resolved.rules}

    successful = registry.apply_rule(
        rule=by_name["guarded_match_output"],
        content="BUILD SUCCESSFUL in 2s\n",
    )
    guarded = registry.apply_rule(
        rule=by_name["guarded_match_output"],
        content="BUILD SUCCESSFUL in 2s\nerror: dependency resolution failed\n",
    )
    empty_fallback = registry.apply_rule(
        rule=by_name["empty_fallback"],
        content="line one\nline two\n",
    )

    assert successful == "gradle: ok"
    assert guarded == "BUILD SUCCESSFUL in 2s\nerror: dependency resolution failed\n"
    assert empty_fallback == "emptier: ok"


def test_declarative_pipeline_keep_lines_branch_filters_and_preserves_order() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "keep_only_failures",
                "match_command": r"^pytest\b",
                "keep_lines": [r"FAILED", r"ERROR"],
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "keep_only_failures")

    transformed = registry.apply_rule(
        rule=rule,
        content=(
            "PASSED test_alpha.py::test_ok\n"
            "FAILED test_beta.py::test_bad\n"
            "ERROR collecting test_gamma.py\n"
            "PASSED test_delta.py::test_ok\n"
        ),
    )

    assert (
        transformed == "FAILED test_beta.py::test_bad\nERROR collecting test_gamma.py\n"
    )


def test_declarative_pipeline_max_lines_stage_truncates_with_marker() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "max_lines_cap",
                "match_command": r"^logs\b",
                "max_lines": 2,
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "max_lines_cap")

    transformed = registry.apply_rule(
        rule=rule,
        content="line-1\nline-2\nline-3\nline-4\n",
    )

    assert transformed == "line-1\nline-2\n... (2 lines truncated)\n"


def test_declarative_pipeline_strip_ansi_stage_independent() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "strip_ansi_only",
                "match_command": r"^ansi\b",
                "strip_ansi": True,
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "strip_ansi_only")

    transformed = registry.apply_rule(
        rule=rule,
        content="\x1b[31mFAIL\x1b[0m plain\n",
    )

    assert transformed == "FAIL plain\n"


def test_declarative_pipeline_replace_stage_independent() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "replace_only",
                "match_command": r"^replace\b",
                "replace": [
                    {"pattern": r"\bERROR\b", "replacement": "ERR"},
                    {"pattern": r"\bWARNING\b", "replacement": "WARN"},
                ],
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "replace_only")

    transformed = registry.apply_rule(
        rule=rule,
        content="ERROR line\nWARNING line\n",
    )

    assert transformed == "ERR line\nWARN line\n"


def test_declarative_pipeline_strip_lines_stage_independent() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "strip_lines_only",
                "match_command": r"^strip\b",
                "strip_lines": [r"^DEBUG"],
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "strip_lines_only")

    transformed = registry.apply_rule(
        rule=rule,
        content="DEBUG one\nINFO two\nDEBUG three\n",
    )

    assert transformed == "INFO two\n"


def test_declarative_pipeline_truncate_lines_at_stage_independent() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "truncate_chars_only",
                "match_command": r"^truncate\b",
                "truncate_lines_at": 6,
            }
        ]
    )
    resolved = registry.resolve(config)
    rule = next(rule for rule in resolved.rules if rule.name == "truncate_chars_only")

    transformed = registry.apply_rule(
        rule=rule,
        content="abcdefghi\n123456789\n",
    )

    assert transformed == "abc...\n123...\n"


def test_declarative_pipeline_head_and_tail_branches_independent() -> None:
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "head_only",
                "match_command": r"^head\b",
                "head_lines": 2,
            },
            {
                "name": "tail_only",
                "match_command": r"^tail\b",
                "tail_lines": 2,
            },
        ]
    )
    resolved = registry.resolve(config)
    by_name = {rule.name: rule for rule in resolved.rules}
    payload = "line-1\nline-2\nline-3\nline-4\n"

    head_out = registry.apply_rule(rule=by_name["head_only"], content=payload)
    tail_out = registry.apply_rule(rule=by_name["tail_only"], content=payload)

    assert head_out == "line-1\nline-2\n... (2 lines omitted)\n"
    assert tail_out == "... (2 lines omitted)\nline-3\nline-4\n"


def test_declarative_rule_matching_supports_tool_category_and_tool_name_pattern() -> (
    None
):
    registry = DeclarativeRuleRegistry()
    config = DynamicCompressionConfig(
        declarative_rules=[
            {
                "name": "category_only",
                "priority": 5,
                "tool_category": "command_execution",
                "match_output": [{"pattern": ".*", "message": "category"}],
            },
            {
                "name": "tool_name_pattern_only",
                "priority": 4,
                "tool_name_pattern": r"^shell$",
                "match_output": [{"pattern": ".*", "message": "tool-name"}],
            },
        ]
    )
    resolved = registry.resolve(config)
    context = _context_for("git status", "On branch main\n")

    matched = registry.match_rule(context=context, rules=resolved.rules)

    assert matched is not None
    assert matched.name == "tool_name_pattern_only"


@pytest.mark.asyncio
async def test_code_rule_precedence_over_declarative_and_explicit_override() -> None:
    strategy_registry = CompressionStrategyRegistry()
    strategy_registry.register("code_wins", _CodeWinsStrategy())
    service = ToolOutputCompressionService(
        strategy_registry=strategy_registry,
        identity_resolver=ToolIdentityResolver(),
        selector=RuleBasedStrategySelector(),
    )
    messages = _build_tool_messages("make all", "Nothing to be done for 'all'.\n")

    base_config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"code_wins": True, "declarative_rule_filter": True},
        rules=[
            CompressionRule(
                name="code_rule",
                priority=1,
                when=CompressionRulePredicate(command_signature="make"),
                pipeline=["code_wins"],
            )
        ],
        declarative_rules=[
            {
                "name": "make_declarative",
                "match_command": r"^make\b",
                "match_output": [
                    {"pattern": r"Nothing to be done", "message": "make: ok"}
                ],
            }
        ],
    )

    default_result = await service.compress_messages(
        messages=messages, config=base_config
    )
    assert default_result.messages[1].content == "code:ok"

    override_config = base_config.model_copy(
        update={
            "declarative_rules": [
                {
                    "name": "make_declarative",
                    "match_command": r"^make\b",
                    "override": True,
                    "match_output": [
                        {"pattern": r"Nothing to be done", "message": "make: ok"}
                    ],
                }
            ]
        }
    )
    override_result = await service.compress_messages(
        messages=messages,
        config=override_config,
    )
    assert override_result.messages[1].content == "make: ok"


@pytest.mark.asyncio
async def test_builtin_declarative_rule_applies_when_no_code_rule_matches() -> None:
    service = _build_service_with_default_registry()
    messages = _build_tool_messages("make all", "Nothing to be done for 'all'.\n")
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=[],
        methods={"declarative_rule_filter": True},
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[1].content == "make: ok"
    assert "declarative_rule_filter" in result.records[0].methods_applied


@pytest.mark.asyncio
async def test_declarative_non_match_stage_timeout_fails_open(monkeypatch) -> None:
    class _TimeoutWorkerResult:
        stdout = ""
        timed_out = True

    def _always_timeout_worker(self, *, snippet, payload):
        del self, snippet, payload
        return _TimeoutWorkerResult()

    monkeypatch.setattr(
        DeclarativeFilterPipeline,
        "_execute_regex_worker",
        _always_timeout_worker,
    )

    service = _build_service_with_default_registry()
    original_content = "drop this line\nkeep this line\n"
    messages = _build_tool_messages("stripper run", original_content)
    config = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        rules=[],
        methods={"declarative_rule_filter": True},
        declarative_rules=[
            {
                "name": "stripper_timeout_rule",
                "match_command": r"^stripper\b",
                "strip_lines": [r"(a+)+$"],
            }
        ],
    )

    result = await service.compress_messages(messages=messages, config=config)

    assert result.messages[1].content == original_content
    assert result.records[0].failed_open is True
    assert any(
        "strip_lines stage" in (method.error or "")
        for method in result.records[0].methods
        if method.name == "declarative_rule_filter"
    )
