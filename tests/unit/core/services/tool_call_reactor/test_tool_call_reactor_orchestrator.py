"""Tests for ToolCallReactorOrchestrator.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.interfaces.end_of_session_service_interface import (
    IEndOfSessionService,
)
from src.core.interfaces.replacement_response_factory_interface import (
    IReplacementResponseFactory,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
    IToolArgumentsFixupPipeline,
)
from src.core.interfaces.tool_arguments_parser_interface import IToolArgumentsParser
from src.core.interfaces.tool_call_deduplicator_interface import IToolCallDeduplicator
from src.core.interfaces.tool_call_extractor_interface import IToolCallExtractor
from src.core.interfaces.tool_call_normalizer_interface import IToolCallNormalizer
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallReactionResult,
)
from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
    ToolCallReactorContext,
)
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)
from src.core.services.tool_call_reactor.orchestrator import (
    ToolCallReactorOrchestrator,
)
from src.tool_call_loop.lifecycle_registry import ToolCallLifecycleRegistry


@pytest.fixture
def mock_extractor() -> Mock:
    """Fixture for a mock tool call extractor."""
    return Mock(spec=IToolCallExtractor)


@pytest.fixture
def mock_normalizer() -> Mock:
    """Fixture for a mock tool call normalizer."""
    return Mock(spec=IToolCallNormalizer)


@pytest.fixture
def mock_stream_context_resolver() -> Mock:
    """Fixture for a mock stream context resolver."""
    resolver = Mock(spec=IToolCallStreamContextResolver)
    resolver.resolve_stream_key.return_value = "test-stream"
    resolver.resolve_buffer_state.return_value = None
    return resolver


@pytest.fixture
def mock_deduplicator() -> Mock:
    """Fixture for a mock deduplicator."""
    dedup = Mock(spec=IToolCallDeduplicator)
    dedup.is_processed.return_value = False
    return dedup


@pytest.fixture
def mock_arguments_parser() -> Mock:
    """Fixture for a mock arguments parser."""
    return Mock(spec=IToolArgumentsParser)


@pytest.fixture
def mock_arguments_fixup_pipeline() -> Mock:
    """Fixture for a mock arguments fixup pipeline."""
    return Mock(spec=IToolArgumentsFixupPipeline)


@pytest.fixture
def mock_reactor() -> AsyncMock:
    """Fixture for a mock tool call reactor."""
    reactor = AsyncMock(spec=IToolCallReactor)
    reactor.process_tool_call.return_value = None
    return reactor


@pytest.fixture
def mock_replacement_factory() -> Mock:
    """Fixture for a mock replacement response factory."""
    return Mock(spec=IReplacementResponseFactory)


@pytest.fixture
def lifecycle_registry() -> ToolCallLifecycleRegistry:
    """Fixture for a lifecycle registry."""
    return ToolCallLifecycleRegistry()


@pytest.fixture
def orchestrator(
    mock_extractor: Mock,
    mock_normalizer: Mock,
    mock_stream_context_resolver: Mock,
    mock_deduplicator: Mock,
    mock_arguments_parser: Mock,
    mock_arguments_fixup_pipeline: Mock,
    mock_reactor: AsyncMock,
    mock_replacement_factory: Mock,
    lifecycle_registry: ToolCallLifecycleRegistry,
) -> ToolCallReactorOrchestrator:
    """Fixture for a ToolCallReactorOrchestrator with mocked dependencies."""
    return ToolCallReactorOrchestrator(
        extractor=mock_extractor,
        normalizer=mock_normalizer,
        stream_context_resolver=mock_stream_context_resolver,
        deduplicator=mock_deduplicator,
        arguments_parser=mock_arguments_parser,
        arguments_fixup_pipeline=mock_arguments_fixup_pipeline,
        reactor=mock_reactor,
        replacement_factory=mock_replacement_factory,
        lifecycle_registry=lifecycle_registry,
    )


class TestBypassPaths:
    """Tests for bypass paths in orchestrator."""

    @pytest.mark.asyncio
    async def test_vtc_tool_calls_bypassed(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
    ) -> None:
        """Test that VTC tool calls are bypassed."""
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={"vtc_tool_calls": True},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        assert result is response
        mock_extractor.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_unchanged(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test that response with no tool calls is returned unchanged."""
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")
        mock_extractor.extract.return_value = []

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        assert result is response
        mock_reactor.process_tool_call.assert_not_called()


class TestProcessingFlow:
    """Tests for the main processing flow."""

    @pytest.mark.asyncio
    async def test_extraction_normalization_parsing_reactor_flow(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test the complete flow: extraction → normalization → parsing → reactor."""
        # Setup mocks
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]

        from src.core.interfaces.tool_call_reactor_internal import (
            NormalizedToolArguments,
            ToolArgumentsEnvelope,
        )

        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        mock_arguments_parser.parse.return_value = envelope
        mock_arguments_fixup_pipeline.apply_fixups.return_value = envelope

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={"backend_name": "test-backend", "model_name": "test-model"},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Verify flow
        mock_extractor.extract.assert_called_once_with(response)
        mock_normalizer.normalize.assert_called_once_with(raw_tool_call)
        mock_deduplicator.filter_new_calls.assert_called_once()
        mock_arguments_parser.parse.assert_called_once_with('{"key": "value"}')
        mock_arguments_fixup_pipeline.apply_fixups.assert_called_once()
        mock_reactor.process_tool_call.assert_called_once()
        assert result is response  # No swallow, so original response returned

    @pytest.mark.asyncio
    async def test_swallow_creates_replacement_response(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
        mock_replacement_factory: Mock,
    ) -> None:
        """Test that swallowed tool calls create replacement response."""
        # Setup mocks
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]

        from src.core.interfaces.tool_call_reactor_internal import (
            NormalizedToolArguments,
            ToolArgumentsEnvelope,
        )

        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        mock_arguments_parser.parse.return_value = envelope
        mock_arguments_fixup_pipeline.apply_fixups.return_value = envelope

        # Reactor swallows the call
        reaction_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response="Blocked by policy",
        )
        mock_reactor.process_tool_call.return_value = reaction_result

        replacement_response = ProcessedResponse(
            content={"choices": [{"message": {"content": "Blocked by policy"}}]},
        )
        mock_replacement_factory.build_replacement.return_value = replacement_response

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={"backend_name": "test-backend", "model_name": "test-model"},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Verify replacement was created and returned
        mock_replacement_factory.build_replacement.assert_called_once()
        assert result is replacement_response

    @pytest.mark.asyncio
    async def test_fail_open_on_reactor_exception(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test that exceptions during reactor invocation don't crash the request."""
        # Setup mocks
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]

        from src.core.interfaces.tool_call_reactor_internal import (
            NormalizedToolArguments,
            ToolArgumentsEnvelope,
        )

        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        mock_arguments_parser.parse.return_value = envelope
        mock_arguments_fixup_pipeline.apply_fixups.return_value = envelope

        # Reactor raises exception
        mock_reactor.process_tool_call.side_effect = Exception("Reactor error")

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={"backend_name": "test-backend", "model_name": "test-model"},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should return original response (fail-open)
        assert result is response
        # Should still mark as processed to prevent retry loops
        mock_deduplicator.mark_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_deduplication_prevents_duplicate_processing(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test that deduplication prevents duplicate processing."""
        # Setup mocks
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        # Deduplicator filters out all calls (already processed)
        mock_deduplicator.filter_new_calls.return_value = []

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should return original response without calling reactor
        assert result is response
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_vs_non_streaming_parity(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test that streaming and non-streaming paths produce same results."""
        # Setup mocks
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]

        from src.core.interfaces.tool_call_reactor_internal import (
            NormalizedToolArguments,
            ToolArgumentsEnvelope,
        )

        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        mock_arguments_parser.parse.return_value = envelope
        mock_arguments_fixup_pipeline.apply_fixups.return_value = envelope

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={"backend_name": "test-backend", "model_name": "test-model"},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        # Test non-streaming
        await orchestrator.handle(response, "test-session", context, is_streaming=False)

        # Verify non-streaming called reactor
        assert mock_reactor.process_tool_call.call_count == 1

        # Reset mocks (but keep call_count tracking)
        call_count_before = mock_reactor.process_tool_call.call_count
        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]
        mock_arguments_parser.parse.return_value = envelope
        mock_arguments_fixup_pipeline.apply_fixups.return_value = envelope

        # Test streaming
        await orchestrator.handle(response, "test-session", context, is_streaming=True)

        # Both should call reactor (same behavior)
        assert mock_reactor.process_tool_call.call_count == call_count_before + 1


class TestFailOpenOnExtractionNormalization:
    """Tests for fail-open behavior during extraction and normalization (requirement 6.2)."""

    @pytest.mark.asyncio
    async def test_extraction_error_returns_unchanged_response(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
    ) -> None:
        """Test that extraction errors don't crash the request (requirement 6.2)."""
        # Setup: extractor raises exception
        mock_extractor.extract.side_effect = Exception("Extraction failed")

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should return original response unchanged (fail-open)
        assert result is response

    @pytest.mark.asyncio
    async def test_normalization_error_returns_unchanged_response(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
    ) -> None:
        """Test that normalization errors don't crash the request (requirement 6.2)."""
        # Setup: extractor succeeds but normalizer raises exception
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.side_effect = Exception("Normalization failed")

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should return original response unchanged (fail-open)
        assert result is response


class TestEndOfSessionCheck:
    """Tests for end-of-session check optimization."""

    @pytest.fixture
    def mock_eos_service(self) -> Mock:
        """Fixture for a mock end-of-session service."""
        eos_service = Mock(spec=IEndOfSessionService)
        eos_service.has_ended = AsyncMock(return_value=False)
        return eos_service

    @pytest.fixture
    def orchestrator_with_eos(
        self,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_stream_context_resolver: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
        mock_replacement_factory: Mock,
        lifecycle_registry: ToolCallLifecycleRegistry,
        mock_eos_service: Mock,
    ) -> ToolCallReactorOrchestrator:
        """Fixture for orchestrator with EoS service."""
        return ToolCallReactorOrchestrator(
            extractor=mock_extractor,
            normalizer=mock_normalizer,
            stream_context_resolver=mock_stream_context_resolver,
            deduplicator=mock_deduplicator,
            arguments_parser=mock_arguments_parser,
            arguments_fixup_pipeline=mock_arguments_fixup_pipeline,
            reactor=mock_reactor,
            replacement_factory=mock_replacement_factory,
            lifecycle_registry=lifecycle_registry,
            end_of_session_service=mock_eos_service,
        )

    @pytest.mark.asyncio
    async def test_skips_processing_when_session_ended(
        self,
        orchestrator_with_eos: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_reactor: AsyncMock,
        mock_eos_service: Mock,
    ) -> None:
        """Test that tool calls are skipped when session has already ended."""
        # Setup: session has ended
        mock_eos_service.has_ended.return_value = True

        # Setup: response has tool calls
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [
            ToolCall(
                id="call_1",
                type="function",
                function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
            )
        ]

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        result = await orchestrator_with_eos.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should return original response without processing tool calls
        assert result is response
        # EoS service should be checked
        mock_eos_service.has_ended.assert_called_once_with("test-session")
        # Reactor should not be called
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_when_session_not_ended(
        self,
        orchestrator_with_eos: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
        mock_eos_service: Mock,
    ) -> None:
        """Test that tool calls are processed when session has not ended."""
        # Setup: session has not ended
        mock_eos_service.has_ended.return_value = False

        # Setup: response has tool calls
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]
        mock_deduplicator.is_processed.return_value = False
        mock_arguments_parser.parse.return_value = Mock(
            normalized_arguments=Mock(root={"key": "value"}),
            parse_outcome="success",
            was_modified_by_fixups=False,
        )
        mock_arguments_fixup_pipeline.apply_fixups.return_value = Mock(
            normalized_arguments=Mock(root={"key": "value"}),
            parse_outcome="success",
            was_modified_by_fixups=False,
        )

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        await orchestrator_with_eos.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should process tool calls normally
        mock_eos_service.has_ended.assert_called_once_with("test-session")
        mock_reactor.process_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_works_without_eos_service(
        self,
        orchestrator: ToolCallReactorOrchestrator,
        mock_extractor: Mock,
        mock_normalizer: Mock,
        mock_deduplicator: Mock,
        mock_arguments_parser: Mock,
        mock_arguments_fixup_pipeline: Mock,
        mock_reactor: AsyncMock,
    ) -> None:
        """Test that orchestrator works when EoS service is not provided."""
        # Setup: response has tool calls
        raw_tool_call = {
            "id": "call_1",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        normalized_tool_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        mock_extractor.extract.return_value = [raw_tool_call]
        mock_normalizer.normalize.return_value = normalized_tool_call
        mock_deduplicator.filter_new_calls.return_value = [tool_call]
        mock_deduplicator.is_processed.return_value = False
        mock_arguments_parser.parse.return_value = Mock(
            normalized_arguments=Mock(root={"key": "value"}),
            parse_outcome="success",
            was_modified_by_fixups=False,
        )
        mock_arguments_fixup_pipeline.apply_fixups.return_value = Mock(
            normalized_arguments=Mock(root={"key": "value"}),
            parse_outcome="success",
            was_modified_by_fixups=False,
        )

        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
        )
        context = ToolCallReactorContext(stream_key="test-stream")

        await orchestrator.handle(
            response, "test-session", context, is_streaming=False
        )

        # Should process tool calls normally (no EoS check)
        mock_reactor.process_tool_call.assert_called_once()
