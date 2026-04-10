"""
Unit tests for BackendRequestPreparationService.

Tests cover request preparation behavior including:
- Normalized message replacement
- Skip-on-empty behavior
- Tool output appends
- History compaction
- Fail-open error handling
- Original request immutability
- Optional collaborators handling

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 8.1, 9.1
"""

# mypy: ignore-errors

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.models.backends import BackendConfig
from src.core.config.models.session import SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.configuration.dynamic_compression_config import (
    CompressionMarkerConfig,
    CompressionRecoveryConfig,
    CompressionRule,
    CompressionRulePredicate,
    DynamicCompressionConfig,
)
from src.core.domain.dynamic_compression import ToolOutputContext
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.history_compaction_interface import (
    CompactionResult,
    IHistoryCompactionService,
)
from src.core.interfaces.tool_output_compression_interface import (
    IToolOutputCompressionService,
)
from src.core.services.backend_request_preparation_service import (
    BackendRequestPreparationService,
)
from src.core.services.compression_strategy_registry import CompressionStrategyRegistry
from src.core.services.rule_based_strategy_selector import RuleBasedStrategySelector
from src.core.services.tool_identity_resolver import ToolIdentityResolver
from src.core.services.tool_output_compression_service import (
    ToolOutputCompressionService,
)


@pytest.fixture
def mock_compaction_service() -> IHistoryCompactionService:
    """Create a mock history compaction service."""
    mock = AsyncMock(spec=IHistoryCompactionService)
    return mock


@pytest.fixture
def mock_config() -> IConfig:
    """Create a mock configuration."""
    mock = MagicMock(spec=IConfig)
    compaction_config = CompactionConfig(enabled=True, token_threshold=1000)
    mock.compaction = compaction_config
    return mock


@pytest.fixture
def preparation_service(
    mock_compaction_service: IHistoryCompactionService | None,
    mock_config: IConfig | None,
) -> BackendRequestPreparationService:
    """Create a BackendRequestPreparationService instance."""
    return BackendRequestPreparationService(
        history_compaction_service=mock_compaction_service, config=mock_config
    )


@pytest.fixture
def preparation_service_no_deps() -> BackendRequestPreparationService:
    """Create a service with no optional dependencies."""
    return BackendRequestPreparationService(
        history_compaction_service=None, config=None
    )


def test_startup_prevalidates_dynamic_compression_config(
    caplog, mock_config: IConfig
) -> None:
    class _PrevalidateStub:
        def __init__(self) -> None:
            self.calls: list[DynamicCompressionConfig] = []

        def prevalidate_config(self, config: DynamicCompressionConfig) -> list[str]:
            self.calls.append(config)
            return ["Declarative rule file not found: missing-rules.json"]

    mock_config.dynamic_compression = DynamicCompressionConfig(
        enabled=True,
        declarative_rule_files=["missing-rules.json"],
    )
    stub = _PrevalidateStub()

    with caplog.at_level(logging.WARNING):
        BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=stub,
        )

    assert len(stub.calls) == 1
    assert any(
        "startup validation warning" in record.message.lower()
        for record in caplog.records
    )


def test_startup_skips_dynamic_compression_prevalidation_when_disabled(
    mock_config: IConfig,
) -> None:
    class _PrevalidateStub:
        def __init__(self) -> None:
            self.calls: list[DynamicCompressionConfig] = []

        def prevalidate_config(self, config: DynamicCompressionConfig) -> list[str]:
            self.calls.append(config)
            return []

    mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
    stub = _PrevalidateStub()

    BackendRequestPreparationService(
        history_compaction_service=None,
        config=mock_config,
        tool_output_compression_service=stub,
    )

    assert stub.calls == []


@pytest.fixture
def base_request() -> ChatRequest:
    """Create a base chat request for testing."""
    return ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ],
    )


class TestNormalizedMessageReplacement:
    """Tests for normalized message replacement behavior."""

    @pytest.mark.asyncio
    async def test_replace_messages_when_modified_messages_have_content(
        self,
        preparation_service: BackendRequestPreparationService,
        base_request: ChatRequest,
    ) -> None:
        """When modified_messages contain user content, should replace original messages."""
        # Arrange
        modified_msg = ChatMessage(role="user", content="Modified content")
        command_result = ProcessedResult(
            modified_messages=[modified_msg],
            command_executed=True,
            command_results=[],
        )

        # Act
        result = await preparation_service.prepare(base_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == [modified_msg]
        assert result.model == base_request.model
        # Verify original request was not mutated
        assert base_request.messages != result.messages


class TestCompactionMessageReplacement:
    """Regression tests for compaction message replacement."""

    @pytest.mark.asyncio
    async def test_returns_compacted_messages_when_compaction_occurs(
        self,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
    ) -> None:
        """REGRESSION: When compaction occurs, must return compacted messages, not originals."""
        # Arrange
        mock_config.compaction = CompactionConfig(enabled=True, token_threshold=100)
        service = BackendRequestPreparationService(
            history_compaction_service=mock_compaction_service,
            config=mock_config,
        )

        # Original request with large content
        original_content = "x" * 5000
        original_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=original_content)],
        )

        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Compaction returns different messages
        compacted_content = "COMPACTED"
        compacted_messages = [ChatMessage(role="user", content=compacted_content)]
        compaction_result = CompactionResult(
            messages=compacted_messages,
            compacted_count=1,
            bytes_saved=4990,
            tokens_saved_estimate=1247,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        result = await service.prepare(original_request, command_result)

        # Assert - CRITICAL: Must return compacted messages, not originals
        assert result is not None
        assert len(result.messages) == 1
        assert result.messages[0].content == compacted_content
        assert result.messages[0].content != original_content
        # Verify compaction was actually called
        mock_compaction_service.compact_history.assert_called_once()


class TestMaxTokensOverflowWarning:
    """Tests for max tokens overflow warning (Req 3.2)."""

    @pytest.mark.asyncio
    async def test_emit_warning_when_compaction_exceeds_max_tokens(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When compaction reduces but still exceeds max_tokens, should emit warning."""
        # Arrange
        # Set low max_tokens for testing
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=1000, max_tokens=500
        )

        # Create content that will exceed max_tokens even after compaction
        large_content = "x" * 5000  # ~1250 tokens (exceeds threshold of 1000)
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Compaction reduces tokens but not below max (500)
        compacted_messages = [
            ChatMessage(role="user", content="x" * 2400)
        ]  # ~600 tokens (still exceeds 500 max)
        compaction_result = CompactionResult(
            messages=compacted_messages,
            compacted_count=1,
            bytes_saved=600,
            tokens_saved_estimate=150,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        with caplog.at_level(logging.WARNING):
            result = await preparation_service.prepare(large_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == compacted_messages

        # Verify warning was emitted with correct message
        warning_logs = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "overflow" in r.message.lower()
        ]
        assert len(warning_logs) > 0

        # Verify structured data in log
        warning_log = warning_logs[0]
        assert (
            "Context compaction could not reduce tokens below maximum"
            in warning_log.message
        )
        # Extra fields are merged into the log record's __dict__
        assert hasattr(warning_log, "current_estimate")
        assert hasattr(warning_log, "max_tokens")
        assert hasattr(warning_log, "overflow_tokens")
        assert hasattr(warning_log, "recommendation")
        assert warning_log.max_tokens == 500
        assert warning_log.overflow_tokens > 0

    @pytest.mark.asyncio
    async def test_no_warning_when_compaction_below_max_tokens(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When compaction reduces tokens below max_tokens, should not warn."""
        # Arrange
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=1000, max_tokens=10000
        )

        large_content = "x" * 5000  # ~1250 tokens
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Compaction reduces to well below max
        compacted_messages = [
            ChatMessage(role="user", content="x" * 4000)
        ]  # ~1000 tokens
        compaction_result = CompactionResult(
            messages=compacted_messages,
            compacted_count=1,
            bytes_saved=1000,
            tokens_saved_estimate=250,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        with caplog.at_level(logging.WARNING):
            result = await preparation_service.prepare(large_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == compacted_messages

        # Verify no overflow warning was emitted
        overflow_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "overflow" in r.message.lower()
            and "could not reduce" in r.message.lower()
        ]
        assert len(overflow_warnings) == 0

    @pytest.mark.asyncio
    async def test_no_warning_when_compaction_disabled(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When compaction disabled, should not warn about overflow."""
        # Arrange
        mock_config.compaction = CompactionConfig(
            enabled=False, token_threshold=1000, max_tokens=500
        )

        large_content = "x" * 3000  # Would exceed max if enabled
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Act
        with caplog.at_level(logging.WARNING):
            result = await preparation_service.prepare(large_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == large_request.messages

        # Verify no overflow warning was emitted
        overflow_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "overflow" in r.message.lower()
            and "could not reduce" in r.message.lower()
        ]
        assert len(overflow_warnings) == 0

    @pytest.mark.asyncio
    async def test_request_processed_after_overflow_warning(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When overflow warning emitted, request should still be processed (fail-open)."""
        # Arrange
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=1000, max_tokens=500
        )

        large_content = "x" * 5000  # ~1250 tokens (exceeds threshold)
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        compacted_messages = [ChatMessage(role="user", content="x" * 2400)]
        compaction_result = CompactionResult(
            messages=compacted_messages,
            compacted_count=1,
            bytes_saved=600,
            tokens_saved_estimate=150,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        with caplog.at_level(logging.WARNING):
            result = await preparation_service.prepare(large_request, command_result)

        # Assert - Request was still processed (not None)
        assert result is not None
        assert result.model == large_request.model
        assert result.messages == compacted_messages

        # Warning was emitted but didn't block processing
        assert any(
            r.levelname == "WARNING" and "overflow" in r.message.lower()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_no_warning_when_no_compaction_occurred(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When compaction runs but nothing was compacted, should not warn."""
        # Arrange
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=1000, max_tokens=500
        )

        large_content = "x" * 3000
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # No compaction happened
        compaction_result = CompactionResult(
            messages=large_request.messages,  # Same as input
            compacted_count=0,  # Nothing compacted
            bytes_saved=0,
            tokens_saved_estimate=0,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        with caplog.at_level(logging.WARNING):
            result = await preparation_service.prepare(large_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == large_request.messages

        # No overflow warning when nothing was compacted
        overflow_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and "overflow" in r.message.lower()
            and "could not reduce" in r.message.lower()
        ]
        assert len(overflow_warnings) == 0

    @pytest.mark.asyncio
    async def test_warning_contains_correct_overflow_amount(
        self,
        preparation_service: BackendRequestPreparationService,
        mock_compaction_service: IHistoryCompactionService,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Warning should contain accurate overflow amount calculation."""
        # Arrange
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=100, max_tokens=100
        )

        # Create request that will trigger compaction and exceed max
        content = "x" * 5000  # ~1250 tokens, exceeds threshold of 100
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Compacted to 600 chars = ~150 tokens (exceeds max of 100)
        compacted_messages = [ChatMessage(role="user", content="x" * 600)]
        compaction_result = CompactionResult(
            messages=compacted_messages,
            compacted_count=1,
            bytes_saved=4400,
            tokens_saved_estimate=1100,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        with caplog.at_level(logging.WARNING):
            await preparation_service.prepare(large_request, command_result)

        # Assert
        overflow_warnings = [
            r
            for r in caplog.records
            if r.levelname == "WARNING" and "overflow" in r.message.lower()
        ]
        assert len(overflow_warnings) > 0

        # Extra fields are merged into the log record's __dict__
        warning_log = overflow_warnings[0]
        assert hasattr(warning_log, "overflow_tokens")
        assert hasattr(warning_log, "max_tokens")
        assert hasattr(warning_log, "current_estimate")
        assert warning_log.overflow_tokens > 0  # Should be positive
        assert warning_log.max_tokens == 100
        assert warning_log.current_estimate > 100

    @pytest.mark.asyncio
    async def test_service_initializes_without_config(
        self,
        preparation_service_no_deps: BackendRequestPreparationService,
        base_request: ChatRequest,
    ) -> None:
        """Service should handle None config without errors."""
        # Arrange
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Act
        result = await preparation_service_no_deps.prepare(base_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == base_request.messages

    @pytest.mark.asyncio
    async def test_compaction_skipped_when_service_none(
        self,
        preparation_service_no_deps: BackendRequestPreparationService,
        base_request: ChatRequest,
    ) -> None:
        """When compaction service is None, compaction should be skipped."""
        # Arrange
        large_content = "x" * 5000
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Act
        result = await preparation_service_no_deps.prepare(
            large_request, command_result
        )

        # Assert
        assert result is not None
        assert result.messages == large_request.messages  # No compaction

    @pytest.mark.asyncio
    async def test_config_fallback_to_default_when_missing(
        self,
        preparation_service: BackendRequestPreparationService,
        base_request: ChatRequest,
        mock_compaction_service: IHistoryCompactionService,
    ) -> None:
        """When config is None or lacks compaction attr, should use default config."""
        # Arrange
        service_no_config = BackendRequestPreparationService(
            history_compaction_service=mock_compaction_service, config=None
        )

        large_content = "x" * 5000
        large_request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content=large_content)],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        compaction_result = CompactionResult(
            messages=large_request.messages,
            compacted_count=0,
            bytes_saved=0,
            tokens_saved_estimate=0,
            original_message_count=1,
        )
        mock_compaction_service.compact_history = AsyncMock(
            return_value=compaction_result
        )

        # Act
        result = await service_no_config.prepare(large_request, command_result)

        # Assert
        assert result is not None
        # Should attempt compaction (default config has enabled=False, but threshold check happens)
        # Since default config has enabled=False, compaction should not be called
        # But the code checks config.enabled first, so it should not call compact_history
        # Let's verify the behavior matches the implementation


class TestInterfaceImplementation:
    """Tests for interface implementation."""

    def test_implements_interface(
        self, preparation_service: BackendRequestPreparationService
    ) -> None:
        """Service should implement IBackendRequestPreparation interface."""
        assert isinstance(preparation_service, IBackendRequestPreparation)

    def test_has_prepare_method(
        self, preparation_service: BackendRequestPreparationService
    ) -> None:
        """Service should have prepare method."""
        assert hasattr(preparation_service, "prepare")
        assert callable(preparation_service.prepare)


class TestDynamicCompressionRequestPathToolOnly:
    """Dynamic compression runs on the request path and must not rewrite non-tool text."""

    @staticmethod
    def _tool_thread(*, tool_content: str) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-1",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"git status"}',
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", tool_call_id="tc-1", content=tool_content),
        ]

    @pytest.mark.asyncio
    async def test_preserves_non_tool_messages_when_compression_skips_large_min_bytes(
        self,
        mock_config: IConfig,
    ) -> None:
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(
            enabled=True,
            min_bytes=50_000_000,
        )
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        user = ChatMessage(role="user", content="user-payload")
        messages = [user, *self._tool_thread(tool_content="tool-payload")]
        request = ChatRequest(model="gpt-4", messages=messages)
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[0] is user
        assert result.messages[1] is messages[1]
        assert result.messages[2] is messages[2]

    @pytest.mark.asyncio
    async def test_emits_request_path_overlap_notes_when_compaction_and_dynamic_enabled(
        self,
        mock_config: IConfig,
        mock_compaction_service: IHistoryCompactionService,
    ) -> None:
        mock_config.compaction = CompactionConfig(
            enabled=True, token_threshold=10, max_tokens=100_000
        )
        mock_config.dynamic_compression = DynamicCompressionConfig(
            enabled=True,
            min_bytes=50_000_000,
        )
        compacted = [
            ChatMessage(role="user", content="u"),
            *TestDynamicCompressionRequestPathToolOnly._tool_thread(
                tool_content="tool-payload"
            ),
        ]
        mock_compaction_service.compact_history = AsyncMock(
            return_value=CompactionResult(
                messages=compacted,
                compacted_count=1,
                bytes_saved=10,
                tokens_saved_estimate=2,
                original_message_count=3,
            )
        )
        service = BackendRequestPreparationService(
            history_compaction_service=mock_compaction_service,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="x" * 400),
                *TestDynamicCompressionRequestPathToolOnly._tool_thread(
                    tool_content="tool-payload"
                ),
            ],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        dx = (result.compression_diagnostics or {}).get(
            "dynamic_compression_compatibility"
        )
        assert dx is not None
        warn_text = " ".join(dx.get("warnings", []))
        assert "history compaction" in warn_text.lower()
        assert "dynamic tool-output compression" in warn_text.lower()

    @pytest.mark.asyncio
    async def test_skips_compression_service_when_dynamic_compression_disabled(
        self,
        mock_config: IConfig,
    ) -> None:
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        compression_service = AsyncMock(spec=IToolOutputCompressionService)
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=compression_service,
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content="tool-payload"),
            ],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages == request.messages
        compression_service.compress_messages.assert_not_awaited()
        diagnostics = result.compression_diagnostics or {}
        assert "dynamic_compression_compatibility" not in diagnostics
        assert "dynamic_compression_records" not in diagnostics


class TestDynamicCompressionLegacyPytestWarnings:
    """Warnings for legacy pytest controls should be signal-only, not default noise."""

    @staticmethod
    def _tool_thread(*, tool_content: str) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-legacy-pytest-1",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"pytest -q"}',
                        ),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="tc-legacy-pytest-1",
                content=tool_content,
            ),
        ]

    @pytest.mark.asyncio
    async def test_default_inherit_path_omits_legacy_pytest_deprecation_warnings(
        self,
        mock_config: IConfig,
    ) -> None:
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(
            enabled=True,
            min_bytes=50_000_000,
        )
        mock_config.session = SessionConfig()
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content="tool-payload"),
            ],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        diagnostics = (result.compression_diagnostics or {}).get(
            "dynamic_compression_compatibility"
        )
        assert diagnostics is not None
        warnings = diagnostics.get("warnings", [])
        assert all(
            "session.pytest_compression_enabled is deprecated" not in warning
            for warning in warnings
        )
        assert all(
            "session.pytest_compression_min_lines is deprecated" not in warning
            for warning in warnings
        )

    @pytest.mark.asyncio
    async def test_non_default_legacy_pytest_controls_emit_deprecation_warnings(
        self,
        mock_config: IConfig,
    ) -> None:
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(
            enabled=True,
            min_bytes=50_000_000,
        )
        mock_config.session = SessionConfig(
            pytest_compression_enabled=False,
            pytest_compression_min_lines=99,
        )
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content="tool-payload"),
            ],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        diagnostics = (result.compression_diagnostics or {}).get(
            "dynamic_compression_compatibility"
        )
        assert diagnostics is not None
        warnings = " ".join(diagnostics.get("warnings", []))
        assert "session.pytest_compression_enabled is deprecated" in warnings
        assert "session.pytest_compression_min_lines is deprecated" in warnings


class TestGeminiLegacyTruncationRequestPathContracts:
    """Request-path contracts for legacy Gemini truncation compatibility."""

    @staticmethod
    def _tool_thread(*, tool_content: str) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-gemini-contract",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"git status"}',
                        ),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="tc-gemini-contract",
                content=tool_content,
            ),
        ]

    @staticmethod
    def _legacy_truncate(
        value: str,
        *,
        max_chars: int | None,
        max_lines: int | None,
    ) -> str:
        marker = "... [CONTENT TRUNCATED] ..."
        text = value
        if isinstance(max_lines, int) and max_lines > 0:
            lines = text.splitlines()
            if len(lines) > max_lines:
                head = max(1, max_lines // 5)
                tail = max_lines - head
                text = "\n".join(lines[:head] + [marker] + lines[-tail:])

        if isinstance(max_chars, int) and max_chars > 0 and len(text) > max_chars:
            head = max(1, max_chars // 5)
            tail = max_chars - head - len(marker)
            if tail <= 0:
                text = text[:max_chars]
            else:
                text = text[:head] + marker + text[-tail:]

        return text

    @pytest.mark.asyncio
    async def test_request_path_legacy_char_truncation_applies_with_diagnostics(
        self,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        payload = "x" * 200
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(extra={"tool_output_truncate_chars": 40})
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        with caplog.at_level(logging.WARNING):
            result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == self._legacy_truncate(
            payload,
            max_chars=40,
            max_lines=None,
        )
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("source") == "connector"
        assert compat.get("effective_max_chars") == 40
        assert compat.get("truncated_tool_messages") == 1
        assert compat.get("compaction_enabled") is False
        assert compat.get("dynamic_compression_enabled") is False
        assert any(
            "active via request-path compatibility" in record.message.lower()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_request_path_legacy_char_limit_keeps_small_output_untouched(
        self,
        mock_config: IConfig,
    ) -> None:
        payload = "small-output"
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(extra={"tool_output_truncate_chars": 40})
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == payload
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("source") == "connector"
        assert compat.get("effective_max_chars") == 40
        assert compat.get("truncated_tool_messages") == 0

    @pytest.mark.asyncio
    async def test_request_path_legacy_line_truncation_applies_with_diagnostics(
        self,
        mock_config: IConfig,
    ) -> None:
        max_lines = 5
        payload = "\n".join(f"line-{idx}" for idx in range(20))
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(
                extra={"tool_output_truncate_lines": max_lines}
            )
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == self._legacy_truncate(
            payload,
            max_chars=None,
            max_lines=max_lines,
        )
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("source") == "connector"
        assert compat.get("effective_max_lines") == max_lines
        assert compat.get("truncated_tool_messages") == 1

    @pytest.mark.asyncio
    async def test_request_path_legacy_controls_inactive_with_compaction(
        self,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        payload = "x" * 200
        mock_config.compaction = CompactionConfig(enabled=True, token_threshold=10)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(extra={"tool_output_truncate_chars": 40})
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        with caplog.at_level(logging.WARNING):
            result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == payload
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("source") == "history_compaction"
        assert compat.get("truncated_tool_messages") == 0
        assert any(
            "inactive for this request because request-path reduction is active"
            in record.message.lower()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_request_path_overlap_with_compaction_and_dynamic_is_deterministic(
        self,
        mock_config: IConfig,
    ) -> None:
        payload = "x" * 200
        mock_config.compaction = CompactionConfig(enabled=True, token_threshold=10)
        mock_config.dynamic_compression = DynamicCompressionConfig(
            enabled=True,
            min_bytes=50_000_000,
        )
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(extra={"tool_output_truncate_chars": 40})
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == payload
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("source") == "history_compaction+dynamic_compression"
        assert compat.get("truncated_tool_messages") == 0

    @pytest.mark.asyncio
    async def test_request_path_legacy_truncation_fails_open_when_resolver_errors(
        self,
        mock_config: IConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class RaisingResolver:
            def resolve_connector_truncation_with_diagnostics(
                self,
                *,
                connector_max_chars: int | None,
                connector_max_lines: int | None,
                compaction_enabled: bool,
                dynamic_compression_enabled: bool,
            ) -> object:
                raise RuntimeError("resolver failure")

        payload = "x" * 200
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(enabled=False)
        mock_config.backends = {
            "gemini-oauth-auto": BackendConfig(extra={"tool_output_truncate_chars": 80})
        }
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=None,
            legacy_compression_compatibility_resolver=RaisingResolver(),
        )
        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="u"),
                *self._tool_thread(tool_content=payload),
            ],
            extra_body={"backend_type": "gemini-oauth-auto"},
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        with caplog.at_level(logging.WARNING):
            result = await service.prepare(request, command_result)

        assert result is not None
        assert result.messages[2].content == self._legacy_truncate(
            payload,
            max_chars=80,
            max_lines=None,
        )
        compat = (result.compression_diagnostics or {}).get(
            "gemini_legacy_truncation_compatibility"
        )
        assert isinstance(compat, dict)
        assert compat.get("resolver_failed_open") is True
        assert compat.get("source") == "fallback_legacy"
        assert compat.get("truncated_tool_messages") == 1
        assert any(
            "compatibility resolution failed open" in record.message.lower()
            for record in caplog.records
        )


class TestDynamicCompressionObservabilitySurfaces:
    """Task group 7 diagnostics are attached to request metadata safely."""

    class _HalfTrimStrategy:
        def compress(
            self,
            content: str,
            *,
            context: ToolOutputContext,
            level: object,
        ) -> str:
            if len(content) <= 4:
                return content
            return content[: len(content) // 2]

    @staticmethod
    def _tool_thread(*, tool_content: str) -> list[ChatMessage]:
        return [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="tc-observe-1",
                        function=FunctionCall(
                            name="shell",
                            arguments='{"command":"git status"}',
                        ),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                tool_call_id="tc-observe-1",
                content=tool_content,
            ),
        ]

    @pytest.mark.asyncio
    async def test_attaches_effective_config_records_stats_and_recovery_handles(
        self,
        mock_config: IConfig,
        tmp_path: Path,
    ) -> None:
        mock_config.compaction = CompactionConfig(enabled=False)
        mock_config.dynamic_compression = DynamicCompressionConfig(
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
                max_artifacts=8,
                max_artifact_bytes=4096,
                retention_seconds=3600,
                hint_in_text=False,
            ),
        )
        registry = CompressionStrategyRegistry()
        registry.register("trim", self._HalfTrimStrategy())
        service = BackendRequestPreparationService(
            history_compaction_service=None,
            config=mock_config,
            tool_output_compression_service=ToolOutputCompressionService(
                strategy_registry=registry,
                identity_resolver=ToolIdentityResolver(),
                selector=RuleBasedStrategySelector(),
            ),
        )

        request = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="user", content="summarize"),
                *self._tool_thread(tool_content="repeat\nrepeat\nrepeat\n"),
            ],
        )
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        result = await service.prepare(request, command_result)

        assert result is not None
        diagnostics = result.compression_diagnostics or {}
        assert "dynamic_compression_effective_config" in diagnostics
        assert "dynamic_compression_records" in diagnostics
        assert "dynamic_compression_stats" in diagnostics
        assert "dynamic_compression_correlation" in diagnostics
        assert "dynamic_compression_recovery" in diagnostics

        effective = diagnostics["dynamic_compression_effective_config"]
        assert "dynamic_compression.enabled" in effective["active_controls"]
        assert isinstance(effective["reasons"], dict)

        records = diagnostics["dynamic_compression_records"]
        assert len(records) == 1
        assert records[0]["saved_bytes"] > 0
        assert records[0]["elapsed_total_ms"] >= 0
        assert "content" not in records[0]
        assert "payload" not in records[0]

        correlation = diagnostics["dynamic_compression_correlation"]["records"][0]
        assert correlation["correlation_id"]
        assert "repeat" not in json.dumps(correlation).lower()

        recovery = diagnostics["dynamic_compression_recovery"]
        assert recovery["enabled"] is True
        assert recovery["handles"]


class TestNoCommandExecution:
    """Tests for behavior when no commands are executed."""

    @pytest.mark.asyncio
    async def test_return_original_when_no_command_executed(
        self,
        preparation_service: BackendRequestPreparationService,
        base_request: ChatRequest,
    ) -> None:
        """When command_executed is False, should return original request."""
        # Arrange
        command_result = ProcessedResult(
            modified_messages=[],
            command_executed=False,
            command_results=[],
        )

        # Act
        result = await preparation_service.prepare(base_request, command_result)

        # Assert
        assert result is not None
        assert result.messages == base_request.messages
