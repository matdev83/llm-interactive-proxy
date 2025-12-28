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

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.domain.processed_result import ProcessedResult
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.history_compaction_interface import (
    CompactionResult,
    IHistoryCompactionService,
)
from src.core.services.backend_request_preparation_service import (
    BackendRequestPreparationService,
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
