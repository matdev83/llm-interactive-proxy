"""
Integration tests for history compaction feature.

These tests verify that:
1. History compaction is correctly invoked in the request pipeline
2. Connectors receive compacted history when appropriate
3. Observability (metrics/logs) hooks fire correctly
4. Token threshold-triggered compaction scenarios work

Requirements: 2.4, 3.1, 3.2, 4.1, 4.2
"""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.configuration.compaction_config import (
    CompactionConfig,
    TokenBudgetConfig,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.history_compaction_interface import CompactionResult
from src.core.services.history_compaction_service import HistoryCompactionService

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


def _make_context() -> RequestContext:
    """Create a minimal RequestContext for testing."""
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
        processing_context=None,
    )


def _make_no_command_result() -> ProcessedResult:
    """Create a ProcessedResult indicating no command was executed."""
    return ProcessedResult(
        modified_messages=[],
        command_executed=False,
        command_results=[],
    )


def _create_tool_call(tool_name: str, tool_call_id: str, args: dict) -> ToolCall:
    """Create a ToolCall with the given parameters."""
    return ToolCall(
        id=tool_call_id,
        type="function",
        function=FunctionCall(
            name=tool_name,
            arguments=json.dumps(args),
        ),
    )


def _create_tool_result_message(
    tool_name: str, content: str, tool_call_id: str
) -> ChatMessage:
    """Create a tool result message."""
    return ChatMessage(
        role="tool",
        content=content,
        tool_call_id=tool_call_id,
        name=tool_name,
    )


def _create_assistant_tool_call_message(tool_calls: list[ToolCall]) -> ChatMessage:
    """Create an assistant message with tool calls."""
    return ChatMessage(
        role="assistant",
        content="",
        tool_calls=tool_calls,
    )


class TestHistoryCompactionPipelineIntegration:
    """Test compaction integration in the request processing pipeline."""

    @pytest.mark.asyncio
    async def test_compaction_invoked_before_backend_request(self) -> None:
        """Verify compaction occurs before the request reaches the backend."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_response = AsyncMock(
            return_value=MagicMock(content="response", metadata={})
        )

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_service.compact_history = AsyncMock(
            return_value=CompactionResult(
                messages=[ChatMessage(role="user", content="compacted")],
                compacted_count=1,
                bytes_saved=100,
                tokens_saved_estimate=25,
                original_message_count=2,
                stale_resources={"view_file:/path/file.py"},
            )
        )

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[
                ChatMessage(role="user", content="view file"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", "file content 1", "call-1"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", "file content 2", "call-2"),
            ],
            stream=False,
        )

        backend_processor.process_backend_request.return_value = ResponseEnvelope(
            content="backend response"
        )

        await manager.prepare_backend_request(
            original_request, _make_no_command_result()
        )

        # Verify compaction was called
        compaction_service.compact_history.assert_awaited_once()
        call_args = compaction_service.compact_history.call_args
        assert len(call_args.args[0]) == 5  # Original messages passed

    @pytest.mark.asyncio
    async def test_compacted_messages_returned_in_prepared_request(self) -> None:
        """Verify the prepared request contains compacted messages."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compacted_messages = [
            ChatMessage(role="user", content="view file"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            ChatMessage(
                role="tool",
                content="[Compacted: view_file:/path/file.py — newer result exists]",
                tool_call_id="call-1",
                name="view_file",
            ),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            _create_tool_result_message("view_file", "latest content", "call-2"),
        ]

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_service.compact_history = AsyncMock(
            return_value=CompactionResult(
                messages=compacted_messages,
                compacted_count=1,
                bytes_saved=500,
                tokens_saved_estimate=125,
                original_message_count=5,
                stale_resources={"view_file:/path/file.py"},
            )
        )

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[
                ChatMessage(role="user", content="view file"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", "old content", "call-1"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", "latest content", "call-2"),
            ],
            stream=False,
        )

        result = await manager.prepare_backend_request(
            original_request, _make_no_command_result()
        )

        # Verify the result uses compacted messages
        assert result is not None
        assert len(result.messages) == 5
        assert "[Compacted:" in str(result.messages[2].content)

    @pytest.mark.asyncio
    async def test_fail_open_returns_original_on_compaction_error(self) -> None:
        """Verify original messages are returned when compaction fails."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_service.compact_history = AsyncMock(
            side_effect=RuntimeError("Compaction internal error")
        )

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
        )

        original_messages = [ChatMessage(role="user", content="hello")]
        original_request = ChatRequest(
            model="gemini",
            messages=original_messages,
            stream=False,
        )

        result = await manager.prepare_backend_request(
            original_request, _make_no_command_result()
        )

        # Should return original request unchanged (fail-open)
        assert result is not None
        assert result.messages == original_messages


class TestHistoryCompactionObservability:
    """Test observability hooks (metrics, structured logging)."""

    @pytest.mark.asyncio
    async def test_structured_log_context_emitted_on_compaction(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify structured log context is emitted when compaction occurs."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_result = CompactionResult(
            messages=[ChatMessage(role="user", content="after")],
            compacted_count=2,
            bytes_saved=1000,
            tokens_saved_estimate=250,
            original_message_count=5,
            stale_resources={"view_file:/a.py", "view_file:/b.py"},
        )
        compaction_service.compact_history = AsyncMock(return_value=compaction_result)

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="before")],
            stream=False,
        )

        with caplog.at_level(logging.INFO):
            await manager.prepare_backend_request(
                original_request, _make_no_command_result()
            )

        # Check log message contains expected information
        assert any(
            "Compacted conversation history" in r.message for r in caplog.records
        )

        # Verify structured data
        record = next(
            r for r in caplog.records if "Compacted conversation history" in r.message
        )
        assert getattr(record, "compacted_messages", None) == 2
        assert getattr(record, "bytes_saved", None) == 1000

    @pytest.mark.asyncio
    async def test_warning_log_emitted_on_compaction_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify warning is logged when compaction fails."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_service.compact_history = AsyncMock(
            side_effect=ValueError("Test compaction error")
        )

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="test")],
            stream=False,
        )

        with caplog.at_level(logging.WARNING):
            await manager.prepare_backend_request(
                original_request, _make_no_command_result()
            )

        log_messages = [r.message for r in caplog.records]
        assert any("History compaction failed" in msg for msg in log_messages)
        assert any("Test compaction error" in msg for msg in log_messages)

    def test_compaction_result_to_metrics_format(self) -> None:
        """Verify CompactionResult.to_metrics() provides expected format."""
        result = CompactionResult(
            messages=[],
            compacted_count=5,
            bytes_saved=2500,
            tokens_saved_estimate=625,
            original_message_count=10,
            stale_resources={"a", "b", "c"},
        )

        metrics = result.to_metrics()

        assert metrics.compaction_messages_compacted == 5
        assert metrics.compaction_bytes_saved == 2500
        assert metrics.compaction_tokens_saved_estimate == 625
        assert metrics.compaction_original_count == 10
        assert metrics.compaction_stale_resources_count == 3
        assert metrics.compaction_failed_open == 0

    def test_compaction_result_to_log_context_format(self) -> None:
        """Verify CompactionResult.to_log_context() provides expected format."""
        result = CompactionResult(
            messages=[],
            compacted_count=3,
            bytes_saved=1500,
            tokens_saved_estimate=375,
            original_message_count=7,
            stale_resources={"view_file:/x.py", "view_file:/y.py"},
        )

        context = result.to_log_context()

        assert context.compacted_count == 3
        assert context.bytes_saved == 1500
        assert context.was_compacted is True
        assert context.failed_open is False
        assert context.stale_resources is not None
        assert "view_file:/x.py" in context.stale_resources

    @pytest.mark.asyncio
    async def test_metrics_included_in_compaction_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify metrics from to_metrics() are included in structured logs (Req 4.1)."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_result = CompactionResult(
            messages=[ChatMessage(role="user", content="after")],
            compacted_count=3,
            bytes_saved=1500,
            tokens_saved_estimate=375,
            original_message_count=8,
            stale_resources={"view_file:/a.py", "view_file:/b.py", "view_file:/c.py"},
        )
        compaction_service.compact_history = AsyncMock(return_value=compaction_result)

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="before")],
            stream=False,
        )

        with caplog.at_level(logging.INFO):
            await manager.prepare_backend_request(
                original_request, _make_no_command_result()
            )

        # Find the compaction log record
        record = next(
            (
                r
                for r in caplog.records
                if "Compacted conversation history" in r.message
            ),
            None,
        )
        assert record is not None, "Compaction log not found"

        # Verify metrics field exists in log extra
        metrics = getattr(record, "metrics", None)
        assert metrics is not None, "Metrics field not found in log extra"
        assert isinstance(metrics, dict), "Metrics should be a dict"

        # Verify all required metrics are present (Req 4.1)
        assert metrics["compaction_messages_compacted"] == 3
        assert metrics["compaction_bytes_saved"] == 1500
        assert metrics["compaction_tokens_saved_estimate"] == 375
        assert metrics["compaction_original_count"] == 8
        assert metrics["compaction_stale_resources_count"] == 3
        assert metrics["compaction_failed_open"] == 0

        # Verify existing log fields are preserved
        assert getattr(record, "original_messages", None) == 8
        assert getattr(record, "compacted_messages", None) == 3
        assert getattr(record, "bytes_saved", None) == 1500
        assert getattr(record, "tokens_saved_estimate", None) == 375

    @pytest.mark.asyncio
    async def test_metrics_to_metrics_called_on_compaction(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Verify to_metrics() is called when compaction occurs."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        compaction_service = MagicMock(spec=HistoryCompactionService)
        compaction_result = CompactionResult(
            messages=[ChatMessage(role="user", content="after")],
            compacted_count=2,
            bytes_saved=1000,
            tokens_saved_estimate=250,
            original_message_count=5,
            stale_resources={"view_file:/a.py"},
        )
        compaction_service.compact_history = AsyncMock(return_value=compaction_result)

        # Mock config with compaction enabled
        app_config = MagicMock(spec=AppConfig)
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=0)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="before")],
            stream=False,
        )

        with caplog.at_level(logging.INFO):
            await manager.prepare_backend_request(
                original_request, _make_no_command_result()
            )

        # Find the compaction log record
        record = next(
            (
                r
                for r in caplog.records
                if "Compacted conversation history" in r.message
            ),
            None,
        )
        assert record is not None

        # Verify metrics field matches the expected output of to_metrics()
        metrics = getattr(record, "metrics", None)
        assert metrics is not None
        expected_metrics = compaction_result.to_metrics().model_dump()
        assert metrics == expected_metrics, "Metrics should match to_metrics() output"


class TestHistoryCompactionTokenThreshold:
    """Test token budget threshold-triggered compaction scenarios."""

    @pytest.mark.asyncio
    async def test_token_threshold_triggers_compaction(self) -> None:
        """Verify compaction is triggered when token threshold is exceeded."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=1000,
            max_tokens=2000,
            min_tool_output_tokens_to_compact=0,
        )

        service = HistoryCompactionService()

        messages = [
            ChatMessage(role="user", content="view file"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            _create_tool_result_message("view_file", "content 1" * 100, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            _create_tool_result_message("view_file", "content 2" * 100, "call-2"),
        ]

        # Should trigger compaction because we have stale tool outputs
        result = await service.compact_history(
            messages, config, current_token_estimate=1500
        )

        assert result.was_compacted
        assert result.bytes_saved > 0

    @pytest.mark.asyncio
    async def test_under_threshold_skips_compaction_when_no_stale(self) -> None:
        """Verify no compaction when under threshold and no stale data."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=5000,
            max_tokens=10000,
        )

        service = HistoryCompactionService()

        messages = [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="hi"),
        ]

        # Token estimate well under threshold and no tool messages
        result = await service.compact_history(
            messages, config, current_token_estimate=100
        )

        # No compaction needed (no stale tool outputs)
        assert not result.was_compacted
        assert result.compacted_count == 0

    def test_token_budget_config_from_compaction_config(self) -> None:
        """Verify TokenBudgetConfig creation from CompactionConfig."""
        config = CompactionConfig(
            enabled=True,
            token_threshold=50000,
            max_tokens=100000,
        )

        budget = TokenBudgetConfig.from_config(config, current_estimate=60000)

        assert budget.compaction_threshold == 50000
        assert budget.max_tokens == 100000
        assert budget.current_estimate == 60000
        assert budget.needs_compaction is True
        assert budget.exceeds_max is False


class TestHistoryCompactionDIIntegration:
    """Test DI container integration for history compaction."""

    def test_history_compaction_service_can_be_instantiated(self) -> None:
        """Verify HistoryCompactionService can be instantiated without DI."""
        service = HistoryCompactionService()
        assert service is not None

    def test_backend_request_manager_accepts_none_compaction_service(self) -> None:
        """Verify BackendRequestManager works without compaction service."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=None,
        )

        assert manager is not None
        assert manager._history_compaction_service is None

    @pytest.mark.asyncio
    async def test_manager_skips_compaction_when_service_is_none(self) -> None:
        """Verify request processing works when compaction service is None."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=None,
        )

        original_request = ChatRequest(
            model="gemini",
            messages=[ChatMessage(role="user", content="hello")],
            stream=False,
        )

        result = await manager.prepare_backend_request(
            original_request, _make_no_command_result()
        )

        # Should return original unchanged
        assert result is not None
        assert result.messages == original_request.messages


class TestHistoryCompactionRealService:
    """Integration tests using real HistoryCompactionService."""

    @pytest.mark.asyncio
    async def test_redaction_disabled_includes_full_paths(self) -> None:
        """Verify stubs include full file paths when redaction disabled (Req 4.5)."""
        service = HistoryCompactionService()
        config = CompactionConfig(
            enabled=True,
            redact_resource_identifiers=False,  # Redaction OFF
            min_tool_output_tokens_to_compact=0,
        )

        messages = [
            ChatMessage(role="user", content="view file"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/secret.py"}
                    )
                ]
            ),
            _create_tool_result_message("view_file", "old content" * 50, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/secret.py"}
                    )
                ]
            ),
            _create_tool_result_message("view_file", "new content", "call-2"),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        compacted_msg = result.messages[2]
        # Full path should be visible in stub
        content_str = (
            compacted_msg.content
            if isinstance(compacted_msg.content, str)
            else str(compacted_msg.content)
        )
        assert "/path/secret.py" in content_str

    @pytest.mark.asyncio
    async def test_redaction_enabled_applies_redact_text(self) -> None:
        """Verify stubs apply redact_text() when redaction enabled (Req 4.5)."""
        service = HistoryCompactionService()
        config = CompactionConfig(
            enabled=True,
            redact_resource_identifiers=True,  # Redaction ON
            min_tool_output_tokens_to_compact=0,
        )

        # Use a path with an API key that should be redacted
        # Note: Using 'ak-proj' prefix with 17+ chars to match API key regex \bak-(ant|sk|proj)[A-Za-z0-9_-]{17,}\b
        messages = [
            ChatMessage(role="user", content="view config"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-1",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message("view_file", "old content" * 50, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-2",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message("view_file", "new content", "call-2"),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        compacted_msg = result.messages[2]
        # API key should be redacted
        content_str = (
            compacted_msg.content
            if isinstance(compacted_msg.content, str)
            else str(compacted_msg.content)
        )
        assert "ak-proj1234567890abcdefg" not in content_str
        assert "***" in content_str
        assert "[COMPACTED]" in content_str

    @pytest.mark.asyncio
    async def test_redaction_redacts_api_keys_in_paths(self) -> None:
        """Verify API keys in paths are redacted (Req 4.5)."""
        service = HistoryCompactionService()
        config = CompactionConfig(
            enabled=True,
            redact_resource_identifiers=True,  # Redaction ON
            min_tool_output_tokens_to_compact=0,
        )

        messages = [
            ChatMessage(role="user", content="view config"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-1",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message("view_file", "old config" * 50, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-2",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message("view_file", "new config", "call-2"),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        compacted_msg = result.messages[2]
        # API key should be redacted
        content_str = (
            compacted_msg.content
            if isinstance(compacted_msg.content, str)
            else str(compacted_msg.content)
        )
        assert "ak-proj1234567890abcdefg" not in content_str
        assert "***" in content_str

    @pytest.mark.asyncio
    async def test_redaction_default_is_false(self) -> None:
        """Verify redaction defaults to OFF for debuggability (Req 4.5)."""
        service = HistoryCompactionService()
        config = CompactionConfig(
            enabled=True,
            min_tool_output_tokens_to_compact=0,
        )  # Default: redact_resource_identifiers=False

        messages = [
            ChatMessage(role="user", content="view file"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                    )
                ]
            ),
            _create_tool_result_message("view_file", "old content" * 50, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                    )
                ]
            ),
            _create_tool_result_message("view_file", "new content", "call-2"),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        compacted_msg = result.messages[2]
        # Full path should be visible (redaction OFF by default)
        content_str = (
            compacted_msg.content
            if isinstance(compacted_msg.content, str)
            else str(compacted_msg.content)
        )
        assert "/path/file.py" in content_str

    @pytest.mark.asyncio
    async def test_redaction_preserves_latest_result(self) -> None:
        """Verify redaction doesn't affect preserved latest result (Req 4.5)."""
        service = HistoryCompactionService()
        config = CompactionConfig(
            enabled=True,
            redact_resource_identifiers=True,  # Redaction ON
            min_tool_output_tokens_to_compact=0,
        )

        # Use paths with API keys to test redaction (use longer key that matches pattern \bak-(ant|sk|proj)[A-Za-z0-9_-]{17,}\b)
        messages = [
            ChatMessage(role="user", content="view config"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-1",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message("view_file", "old content" * 50, "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file",
                        "call-2",
                        {
                            "AbsolutePath": "/home/user/ak-proj1234567890abcdefg/config.json"
                        },
                    )
                ]
            ),
            _create_tool_result_message(
                "view_file", "latest important content", "call-2"
            ),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        # First result (compacted) should have API key redacted
        compacted_msg = result.messages[2]
        compacted_content = (
            compacted_msg.content
            if isinstance(compacted_msg.content, str)
            else str(compacted_msg.content)
        )
        assert "ak-proj1234567890abcdefg" not in compacted_content

        # Latest result should be preserved with full content
        latest_msg = result.messages[4]
        latest_content = (
            latest_msg.content
            if isinstance(latest_msg.content, str)
            else str(latest_msg.content)
        )
        assert "latest important content" in latest_content

    @pytest.mark.asyncio
    async def test_real_service_compacts_stale_tool_outputs(self) -> None:
        """Verify real service correctly identifies and compacts stale outputs."""
        service = HistoryCompactionService()
        config = CompactionConfig(enabled=True)

        messages = [
            ChatMessage(role="user", content="view file.py"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            _create_tool_result_message(
                "view_file", "def old_function(): pass\n" * 50, "call-1"
            ),
            ChatMessage(role="assistant", content="I see the old function."),
            ChatMessage(role="user", content="view file.py again"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/file.py"}
                    ),
                ]
            ),
            _create_tool_result_message(
                "view_file", "def new_function(): return 42", "call-2"
            ),
        ]

        result = await service.compact_history(messages, config)

        assert result.was_compacted
        assert result.compacted_count == 1
        assert result.bytes_saved > 0

        # The first tool result message (index 2) should be replaced with a stub
        compacted_tool_msg = result.messages[2]
        assert "[COMPACTED]" in str(compacted_tool_msg.content)
        assert compacted_tool_msg.tool_call_id == "call-1"

        # The second tool result message (index 6) should be preserved
        preserved_tool_msg = result.messages[6]
        assert "def new_function" in str(preserved_tool_msg.content)

    @pytest.mark.asyncio
    async def test_real_service_preserves_different_resources(self) -> None:
        """Verify service preserves outputs from different resources."""
        service = HistoryCompactionService()
        config = CompactionConfig(enabled=True)

        messages = [
            ChatMessage(role="user", content="view files"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-1", {"AbsolutePath": "/path/a.py"}
                    ),
                ]
            ),
            _create_tool_result_message("view_file", "content of a.py", "call-1"),
            _create_assistant_tool_call_message(
                [
                    _create_tool_call(
                        "view_file", "call-2", {"AbsolutePath": "/path/b.py"}
                    ),
                ]
            ),
            _create_tool_result_message("view_file", "content of b.py", "call-2"),
        ]

        result = await service.compact_history(messages, config)

        # Different files should not be compacted against each other
        assert not result.was_compacted
        assert result.compacted_count == 0

    @pytest.mark.asyncio
    async def test_end_to_end_with_backend_request_manager(self) -> None:
        """End-to-end test of compaction through BackendRequestManager."""
        backend_processor = AsyncMock()
        response_processor = MagicMock()
        response_processor.process_response = AsyncMock(
            return_value=MagicMock(content="response", metadata={})
        )

        compaction_service = HistoryCompactionService()

        # Mock config with compaction enabled and appropriate threshold
        app_config = MagicMock(spec=AppConfig)
        # Low threshold to ensure compaction runs on this request
        app_config.compaction = CompactionConfig(enabled=True, token_threshold=100)

        manager = create_backend_request_manager(
            backend_processor=backend_processor,
            response_processor=response_processor,
            history_compaction_service=compaction_service,
            config=app_config,
        )

        # Build a request with stale tool outputs (proper structure)
        # Content is sized to exceed the 100K token threshold (default)
        # ~480K characters ≈ ~120K tokens at 4 chars/token average
        large_content = "old version " * 40000  # ~480K chars
        original_request = ChatRequest(
            model="gemini",
            messages=[
                ChatMessage(role="user", content="view the file"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-1", {"AbsolutePath": "/project/main.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", large_content, "call-1"),
                ChatMessage(role="assistant", content="I see the old version."),
                ChatMessage(role="user", content="view it again"),
                _create_assistant_tool_call_message(
                    [
                        _create_tool_call(
                            "view_file", "call-2", {"AbsolutePath": "/project/main.py"}
                        ),
                    ]
                ),
                _create_tool_result_message("view_file", "new version" * 50, "call-2"),
            ],
            stream=False,
        )

        prepared_request = await manager.prepare_backend_request(
            original_request, _make_no_command_result()
        )

        assert prepared_request is not None

        # Verify compaction occurred
        assert len(prepared_request.messages) == 7

        # First tool result (index 2) should be compacted
        first_tool = prepared_request.messages[2]
        assert "[COMPACTED]" in str(first_tool.content)
        assert first_tool.tool_call_id == "call-1"

        # Latest tool result (index 6) should be preserved
        second_tool = prepared_request.messages[6]
        assert "new version" in str(second_tool.content)
        assert second_tool.tool_call_id == "call-2"
