"""
Property-based tests for hybrid backend sentinel coordination.

Feature: streaming-pipeline-refactor, Property 16: Hybrid sentinel coordination

These tests verify that hybrid backends properly coordinate sentinels across
reasoning and execution phases, ensuring exactly one sentinel is emitted after
both phases complete.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.connectors.hybrid import HybridConnector
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


# Test data generators
@st.composite
def reasoning_output_strategy(draw: Any) -> str:
    """Generate reasoning output text."""
    # Generate non-empty reasoning text
    text = draw(
        st.text(
            min_size=5,
            max_size=100,
            alphabet=st.characters(blacklist_categories=["Cs"]),
        )
    )
    return f"<thinking>{text}</thinking>"


@st.composite
def execution_chunks_strategy(draw: Any) -> list[ProcessedResponse]:
    """Generate execution phase chunks."""
    num_chunks = draw(st.integers(min_value=1, max_value=10))
    chunks = []

    for i in range(num_chunks):
        content = draw(st.text(min_size=1, max_size=100))
        # Create SSE-formatted chunk
        sse_content = (
            f'data: {{"choices": [{{"delta": {{"content": "{content}"}}}}]}}\n\n'
        )
        chunks.append(
            ProcessedResponse(
                content=sse_content,
                usage=None,
                metadata={"index": i},
            )
        )

    # Add final [DONE] marker
    chunks.append(
        ProcessedResponse(
            content="data: [DONE]\n\n",
            usage=None,
            metadata={"is_done": True},
        )
    )

    return chunks


def create_mock_config(reasoning_probability: float = 1.0) -> MagicMock:
    """Create a mock config for hybrid backend tests."""
    mock_config = MagicMock()
    mock_config.backends.hybrid_reasoning_model_timeout = 30
    mock_config.backends.hybrid_execution_model_timeout = 30
    mock_config.backends.reasoning_injection_probability = reasoning_probability
    mock_config.backends.hybrid_reasoning_force_initial_turns = 0
    mock_config.backends.hybrid_backend_repeat_messages = False
    mock_config.backends.disable_hybrid_backend = False
    mock_config.backends.hybrid_reasoning_latency_threshold = 0.0
    mock_config.backends.hybrid_reasoning_backoff_turns = 0
    return mock_config


class TestHybridSentinelCoordination:
    """Test hybrid backend sentinel coordination properties."""

    @pytest.mark.asyncio
    @given(
        reasoning_output=reasoning_output_strategy(),
        execution_chunks=execution_chunks_strategy(),
    )
    @settings(max_examples=5, deadline=5000)
    async def test_property_16_single_sentinel_after_both_phases(
        self,
        reasoning_output: str,
        execution_chunks: list[ProcessedResponse],
    ) -> None:
        """
        Property 16: Hybrid sentinel coordination

        For any hybrid backend stream, exactly one [DONE] sentinel should be
        emitted after both reasoning and execution phases complete.

        Validates: Requirements 6.5
        """
        # Create hybrid connector with mocked dependencies
        connector = HybridConnector(
            client=MagicMock(),
            config=create_mock_config(reasoning_probability=1.0),
            translation_service=MagicMock(),
            backend_registry=MagicMock(),
        )

        # Create mock execution response stream
        async def mock_execution_stream():
            for chunk in execution_chunks:
                yield chunk

        execution_response = StreamingResponseEnvelope(
            content=mock_execution_stream(),
            media_type="text/event-stream",
        )

        # Mock the reasoning phase to return reasoning output
        with patch.object(
            connector,
            "_execute_reasoning_phase",
            new_callable=AsyncMock,
        ) as mock_reasoning:
            # Configure reasoning phase mock
            from src.connectors.hybrid import ReasoningPhaseResult

            mock_reasoning.return_value = ReasoningPhaseResult(
                text=reasoning_output,
                complete=True,
                tool_calls=[],
                raw_chunks=[],
                media_type="text/event-stream",
                headers=None,
            )

            # Mock the execution phase to return the execution response
            with patch.object(
                connector,
                "_execute_execution_phase",
                new_callable=AsyncMock,
            ) as mock_execution:
                mock_execution.return_value = execution_response

                # Mock the augment messages method
                with patch.object(
                    connector,
                    "_augment_messages",
                    return_value=[{"role": "user", "content": "test"}],
                ):
                    # Call chat_completions
                    response = await connector.chat_completions(
                        request_data={
                            "model": "hybrid:[test:model1,test:model2]",
                            "messages": [{"role": "user", "content": "test"}],
                            "stream": True,
                        },
                        processed_messages=[{"role": "user", "content": "test"}],
                        effective_model="hybrid:[test:model1,test:model2]",
                        identity=None,
                    )

                    # Collect all chunks from the response
                    chunks = []
                    if (
                        isinstance(response, StreamingResponseEnvelope)
                        and response.content
                    ):
                        async for chunk in response.content:
                            chunks.append(chunk)

                    # Count [DONE] markers
                    done_count = 0
                    for chunk in chunks:
                        content = chunk.content
                        if isinstance(content, bytes):
                            content = content.decode("utf-8")
                        if isinstance(content, str) and "[DONE]" in content:
                            done_count += 1

                    # Property: Exactly one [DONE] marker should be emitted
                    assert done_count == 1, (
                        f"Expected exactly 1 [DONE] marker after both phases, "
                        f"but got {done_count}. "
                        f"Chunks: {[c.content for c in chunks]}"
                    )

                    # Verify reasoning chunk was emitted before execution chunks
                    has_reasoning = False
                    reasoning_index = -1
                    execution_start_index = -1

                    for i, chunk in enumerate(chunks):
                        content = chunk.content
                        if isinstance(content, bytes):
                            content = content.decode("utf-8")

                        # Check for reasoning content
                        if isinstance(content, str) and "reasoning" in content.lower():
                            has_reasoning = True
                            if reasoning_index == -1:
                                reasoning_index = i

                        # Check for execution content (non-reasoning, non-done)
                        if (
                            isinstance(content, str)
                            and "reasoning" not in content.lower()
                            and "[DONE]" not in content
                            and content.strip()
                            and execution_start_index == -1
                        ):
                            execution_start_index = i

                    # If we have reasoning, it should come before execution
                    if has_reasoning and execution_start_index != -1:
                        assert reasoning_index < execution_start_index, (
                            f"Reasoning chunk should come before execution chunks. "
                            f"Reasoning at index {reasoning_index}, "
                            f"execution starts at {execution_start_index}"
                        )

    @pytest.mark.asyncio
    async def test_hybrid_sentinel_with_tool_calls(self) -> None:
        """
        Test that hybrid backend emits single sentinel when reasoning produces tool calls.

        When reasoning phase produces tool calls without execution, exactly one
        sentinel should still be emitted.
        """
        # Create hybrid connector with mocked dependencies
        connector = HybridConnector(
            client=MagicMock(),
            config=create_mock_config(reasoning_probability=1.0),
            translation_service=MagicMock(),
            backend_registry=MagicMock(),
        )

        # Mock the reasoning phase to return tool calls
        with patch.object(
            connector,
            "_execute_reasoning_phase",
            new_callable=AsyncMock,
        ) as mock_reasoning:
            from src.connectors.hybrid import ReasoningPhaseResult

            mock_reasoning.return_value = ReasoningPhaseResult(
                text="",  # No reasoning text
                complete=True,
                tool_calls=[
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "test_function", "arguments": "{}"},
                    }
                ],
                raw_chunks=[],
                media_type="text/event-stream",
                headers=None,
            )

            # Call chat_completions
            response = await connector.chat_completions(
                request_data={
                    "model": "hybrid:[test:model1,test:model2]",
                    "messages": [{"role": "user", "content": "test"}],
                    "stream": True,
                },
                processed_messages=[{"role": "user", "content": "test"}],
                effective_model="hybrid:[test:model1,test:model2]",
                identity=None,
            )

            # Collect all chunks from the response
            chunks = []
            if isinstance(response, StreamingResponseEnvelope) and response.content:
                async for chunk in response.content:
                    chunks.append(chunk)

            # Count [DONE] markers
            done_count = 0
            for chunk in chunks:
                content = chunk.content
                if isinstance(content, bytes):
                    content = content.decode("utf-8")
                if isinstance(content, str) and "[DONE]" in content:
                    done_count += 1

            # Property: Exactly one [DONE] marker should be emitted
            assert done_count == 1, (
                f"Expected exactly 1 [DONE] marker for tool call response, "
                f"but got {done_count}"
            )

    @pytest.mark.asyncio
    async def test_hybrid_sentinel_without_reasoning(self) -> None:
        """
        Test that hybrid backend emits single sentinel when reasoning is skipped.

        When reasoning phase is skipped (probability-based), exactly one sentinel
        should still be emitted after execution.
        """
        # Create hybrid connector with mocked dependencies (skip reasoning)
        connector = HybridConnector(
            client=MagicMock(),
            config=create_mock_config(reasoning_probability=0.0),
            translation_service=MagicMock(),
            backend_registry=MagicMock(),
        )

        # Create mock execution response stream
        async def mock_execution_stream():
            yield ProcessedResponse(
                content='data: {"choices": [{"delta": {"content": "test"}}]}\n\n',
                usage=None,
                metadata={},
            )
            yield ProcessedResponse(
                content="data: [DONE]\n\n",
                usage=None,
                metadata={"is_done": True},
            )

        execution_response = StreamingResponseEnvelope(
            content=mock_execution_stream(),
            media_type="text/event-stream",
        )

        # Mock both reasoning and execution phases
        with patch.object(
            connector,
            "_execute_reasoning_phase",
            new_callable=AsyncMock,
        ) as mock_reasoning:
            # Configure reasoning phase to be skipped (returns None)
            from src.connectors.hybrid import ReasoningPhaseResult

            mock_reasoning.return_value = ReasoningPhaseResult(
                text="",
                complete=True,
                tool_calls=[],
                raw_chunks=[],
                media_type="text/event-stream",
                headers=None,
            )

            with patch.object(
                connector,
                "_execute_execution_phase",
                new_callable=AsyncMock,
            ) as mock_execution:
                mock_execution.return_value = execution_response

                # Mock the augment messages method
                with patch.object(
                    connector,
                    "_augment_messages",
                    return_value=[{"role": "user", "content": "test"}],
                ):
                    # Call chat_completions
                    response = await connector.chat_completions(
                        request_data={
                            "model": "hybrid:[test:model1,test:model2]",
                            "messages": [{"role": "user", "content": "test"}],
                            "stream": True,
                        },
                        processed_messages=[{"role": "user", "content": "test"}],
                        effective_model="hybrid:[test:model1,test:model2]",
                        identity=None,
                    )

                    # Collect all chunks from the response
                    chunks = []
                    if (
                        isinstance(response, StreamingResponseEnvelope)
                        and response.content
                    ):
                        async for chunk in response.content:
                            chunks.append(chunk)

                    # Count [DONE] markers
                    done_count = 0
                    for chunk in chunks:
                        content = chunk.content
                        if isinstance(content, bytes):
                            content = content.decode("utf-8")
                        if isinstance(content, str) and "[DONE]" in content:
                            done_count += 1

                    # Property: Exactly one [DONE] marker should be emitted
                    assert done_count == 1, (
                        f"Expected exactly 1 [DONE] marker when reasoning is skipped, "
                        f"but got {done_count}"
                    )
