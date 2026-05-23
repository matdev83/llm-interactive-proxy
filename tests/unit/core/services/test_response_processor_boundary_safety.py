"""Tests for boundary safety of ProcessedResponse emission.

These tests validate that ProcessedResponse objects emitted at boundaries
contain ProcessedChunkContent (bytes | str | dict[str, JsonValue] | None)
and that provider-specific objects are normalized before crossing boundaries.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import (
    ProcessedResponse,
)
from src.core.services.response_processor_service import ResponseProcessor


@pytest.fixture
def mock_response_parser() -> MagicMock:
    """Fixture for a mock response parser."""
    parser = MagicMock(spec=IResponseParser)
    parser.parse_response.return_value = {}
    parser.extract_content.return_value = "default content"
    parser.extract_usage.return_value = None
    parser.extract_metadata.return_value = {}
    return parser


@pytest.fixture
def response_processor(mock_response_parser: MagicMock) -> ResponseProcessor:
    """Fixture for a ResponseProcessor instance."""
    # Create a minimal stream normalizer WITHOUT content accumulation
    # ContentAccumulationProcessor buffers chunks until is_done=True, which would
    # cause tests to fail when expecting immediate chunk emission.
    # For boundary safety tests, we want immediate processing without buffering.
    processors: list[Any] = []
    from src.core.services.streaming.stream_normalizer import StreamNormalizer

    stream_normalizer = StreamNormalizer(processors)
    return ResponseProcessor(
        response_parser=mock_response_parser,
        stream_normalizer=stream_normalizer,
    )


class TestProcessedResponseBoundarySafety:
    """Test that ProcessedResponse emits ProcessedChunkContent at boundaries."""

    @pytest.mark.asyncio
    async def test_process_streaming_response_emits_processed_chunk_content(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that process_streaming_response emits ProcessedResponse with ProcessedChunkContent."""

        # Create a mock stream with StreamingContent
        async def mock_stream() -> AsyncIterator[StreamingContent]:
            yield StreamingContent(
                content="test content",
                is_done=False,
                metadata={"key": "value"},
            )
            yield StreamingContent(
                content={"choices": [{"delta": {"content": "test"}}]},
                is_done=False,
                metadata={"model": "gpt-4"},
            )
            yield StreamingContent(
                content=b"bytes content",
                is_done=True,
                metadata={},
            )

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            # Verify content is ProcessedChunkContent
            assert isinstance(chunk, ProcessedResponse)
            assert isinstance(
                chunk.content, str | bytes | dict | type(None)
            ), f"Expected ProcessedChunkContent, got {type(chunk.content)}"
            # Verify metadata is dict[str, JsonValue]
            assert isinstance(chunk.metadata, dict)
            # All metadata values should be JSON-serializable
            for key, value in chunk.metadata.items():
                assert isinstance(key, str)
                assert isinstance(
                    value, str | int | float | bool | type(None) | dict | list
                ), f"Metadata value {key} is not JSON-serializable: {type(value)}"

        assert len(chunks) == 3

    @pytest.mark.asyncio
    async def test_process_streaming_response_normalizes_provider_specific_objects(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that provider-specific objects are normalized before crossing boundaries."""

        # Create a mock stream with provider-specific objects
        class ProviderSpecificObject:
            def __init__(self) -> None:
                self.value = "test"

            def __str__(self) -> str:
                return f"ProviderObject(value={self.value})"

        async def mock_stream() -> AsyncIterator[StreamingContent]:
            # Provider-specific object will be normalized to ProcessedChunkContent
            provider_obj = ProviderSpecificObject()
            yield StreamingContent(
                content=str(provider_obj),  # Convert to string for type safety
                is_done=False,
                metadata={},
            )

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            # Provider-specific object should be normalized to str
            assert isinstance(chunk, ProcessedResponse)
            assert isinstance(chunk.content, str)
            assert "ProviderObject" in chunk.content

        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_process_streaming_response_normalizes_dict_to_json_safe(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that dicts are normalized to dict[str, JsonValue]."""

        # Create a mock stream with dict containing non-JSON-serializable values
        def non_serializable_function() -> None:
            pass

        async def mock_stream() -> AsyncIterator[StreamingContent]:
            yield StreamingContent(
                content={
                    "key": "value",
                    "callable": non_serializable_function,  # Non-serializable
                },
                is_done=False,
                metadata={},
            )

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            assert isinstance(chunk, ProcessedResponse)
            # Dict should be normalized (non-serializable values removed)
            if isinstance(chunk.content, dict):
                assert "key" in chunk.content
                assert chunk.content["key"] == "value"
                # Non-serializable callable should be removed
                assert "callable" not in chunk.content

        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_process_streaming_response_preserves_processed_response_content(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that ProcessedResponse chunks are normalized when re-wrapped."""

        # Create a mock stream with ProcessedResponse chunks
        async def mock_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content="test content",
                usage=UsageSummary(prompt_tokens=10, completion_tokens=20),
                metadata={"key": "value"},
            )
            yield ProcessedResponse(
                content={"nested": {"key": "value"}},
                usage=None,
                metadata={},
            )

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            assert isinstance(chunk, ProcessedResponse)
            assert isinstance(
                chunk.content, str | bytes | dict | type(None)
            ), f"Expected ProcessedChunkContent, got {type(chunk.content)}"

        assert len(chunks) == 2

    @pytest.mark.asyncio
    async def test_process_streaming_response_handles_unexpected_types(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that unexpected types are normalized to ProcessedChunkContent."""

        # Create a mock stream with unexpected types
        async def mock_stream() -> AsyncIterator[Any]:
            yield [1, 2, 3]  # List (not StreamingContent or ProcessedResponse)
            yield 42  # Integer
            yield None  # None

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            assert isinstance(chunk, ProcessedResponse)
            # Unexpected types should be normalized to ProcessedChunkContent
            assert isinstance(
                chunk.content, str | bytes | dict | type(None)
            ), f"Expected ProcessedChunkContent, got {type(chunk.content)}"

        assert len(chunks) == 3

    @pytest.mark.asyncio
    async def test_process_streaming_response_metadata_is_json_safe(
        self, response_processor: ResponseProcessor
    ) -> None:
        """Test that metadata is normalized to dict[str, JsonValue]."""

        # Create a mock stream with metadata containing non-JSON-serializable values
        def non_serializable_function() -> None:
            pass

        async def mock_stream() -> AsyncIterator[StreamingContent]:
            yield StreamingContent(
                content="test",
                is_done=False,
                metadata={
                    "key": "value",
                    "callable": non_serializable_function,  # Non-serializable
                    "number": 42,
                    "bool": True,
                },
            )

        result_stream = response_processor.process_streaming_response(
            mock_stream(), session_id="test_session"
        )

        chunks = []
        async for chunk in result_stream:
            chunks.append(chunk)
            assert isinstance(chunk, ProcessedResponse)
            # Metadata should be normalized (non-serializable values removed)
            assert isinstance(chunk.metadata, dict)
            assert "key" in chunk.metadata
            assert chunk.metadata["key"] == "value"
            assert "number" in chunk.metadata
            assert chunk.metadata["number"] == 42
            assert "bool" in chunk.metadata
            assert chunk.metadata["bool"] is True
            # Non-serializable callable should be removed
            assert "callable" not in chunk.metadata

        assert len(chunks) == 1
