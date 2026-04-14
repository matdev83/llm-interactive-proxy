from __future__ import annotations

import json

import pytest
from src.core.config.app_config import AppConfig
from src.core.config.models.backends import BackendConfig
from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionMarkerConfig,
    DynamicCompressionConfig,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.services.backend_request_preparation_service import (
    BackendRequestPreparationService,
)
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


def _noop_result() -> ProcessedResult:
    return ProcessedResult(
        modified_messages=[],
        command_executed=False,
        command_results=[],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_declarative_rule_file_applies_in_request_path_and_preserves_message_binding(
    tmp_path,
) -> None:
    rule_file = tmp_path / "declarative_rules.json"
    rule_file.write_text(
        json.dumps(
            {
                "declarative_rules": [
                    {
                        "name": "gradle_success_summary",
                        "match_command": r"^gradle\b",
                        "match_output": [
                            {"pattern": "BUILD SUCCESSFUL", "message": "gradle: ok"}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    config = AppConfig()
    config.compaction = CompactionConfig(enabled=False)
    config.dynamic_compression = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"declarative_rule_filter": True},
        rules=[],
        declarative_rule_files=[str(rule_file)],
    )
    service = BackendRequestPreparationService(
        history_compaction_service=None,
        config=config,
        tool_output_compression_service=ToolOutputCompressionService(),
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="run checks"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-gradle",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"gradle test"}',
                        ),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="tc-gradle",
                content="BUILD SUCCESSFUL in 2s\n",
            ),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-git",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"git status"}',
                        ),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="tc-git",
                content="On branch main\nnothing to commit\n",
            ),
        ],
    )

    before_pairs = [(msg.role, msg.tool_call_id) for msg in request.messages]
    prepared = await service.prepare(request, _noop_result())
    assert prepared is not None

    after_pairs = [(msg.role, msg.tool_call_id) for msg in prepared.messages]
    assert after_pairs == before_pairs
    assert prepared.messages[2].content == "gradle: ok"
    assert prepared.messages[4].content == "On branch main\nnothing to commit\n"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_request_path_overlap_prevents_double_reduction_with_legacy_limits() -> (
    None
):
    config = AppConfig()
    config.compaction = CompactionConfig(enabled=False)
    config.dynamic_compression = DynamicCompressionConfig(
        enabled=True,
        min_bytes=0,
        marker=CompressionMarkerConfig(enabled=False),
        methods={"declarative_rule_filter": True},
        rules=[],
        declarative_rules=[
            {
                "name": "pytest_failure_summary",
                "match_command": r"^pytest\b",
                "match_output": [
                    {"pattern": r"FAILED", "message": "pytest: failure summary"}
                ],
            }
        ],
    )
    config.mutate_backends(
        {
            "gemini-oauth-auto": BackendConfig(
                extra={"tool_output_truncate_chars": 40}
            ),
        }
    )
    service = BackendRequestPreparationService(
        history_compaction_service=None,
        config=config,
        tool_output_compression_service=ToolOutputCompressionService(),
    )

    payload = (
        "FAILED test_mod.py::test_case\n"
        "E AssertionError: expected something very long and detailed\n"
    )
    request = ChatRequest(
        model="gpt-4",
        extra_body={"backend_type": "gemini-oauth-auto"},
        messages=[
            ChatMessage(role="user", content="summarize failure"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-pytest",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"pytest -q"}',
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", tool_call_id="tc-pytest", content=payload),
        ],
    )

    before_pairs = [(msg.role, msg.tool_call_id) for msg in request.messages]
    prepared = await service.prepare(request, _noop_result())
    assert prepared is not None

    after_pairs = [(msg.role, msg.tool_call_id) for msg in prepared.messages]
    assert after_pairs == before_pairs
    assert prepared.messages[2].content == "pytest: failure summary"
    assert "... [CONTENT TRUNCATED] ..." not in str(prepared.messages[2].content)

    diagnostics = prepared.compression_diagnostics or {}
    compat = diagnostics.get("gemini_legacy_truncation_compatibility")
    assert isinstance(compat, dict)
    assert compat.get("source") == "dynamic_compression"
    assert compat.get("truncated_tool_messages") == 0
