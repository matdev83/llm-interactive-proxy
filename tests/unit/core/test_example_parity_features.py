"""
Tests for example parity features demonstrating migration pattern.

These tests verify that the example features maintain equivalent behavior
between streaming and non-streaming paths, demonstrating the parity pattern.
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.interfaces.response_processor_interface import (
    FeatureCapability,
    ProcessedResponse,
)
from src.core.services.example_parity_feature import (
    ContentFilterFeature,
    ContentTransformFeature,
    ResponseLoggingFeature,
    StreamingOnlyMetricsFeature,
)


class TestContentTransformFeature:
    """Tests for ContentTransformFeature demonstrating parity."""

    @pytest.mark.asyncio
    async def test_non_streaming_applies_prefix_and_suffix(self):
        """Test that non-streaming applies full transformation."""
        feature = ContentTransformFeature(prefix="[START]", suffix="[END]")
        response = ProcessedResponse(content="hello")

        result = await feature.process(response, "session1", {}, is_streaming=False)

        assert result.content == "[START]hello[END]"

    @pytest.mark.asyncio
    async def test_streaming_applies_prefix_to_first_chunk(self):
        """Test that streaming applies prefix only to first chunk."""
        feature = ContentTransformFeature(prefix="[START]", suffix="[END]")
        context: dict[str, Any] = {}

        # First chunk
        chunk1 = ProcessedResponse(content="hello ")
        result1 = await feature.process(chunk1, "session1", context, is_streaming=True)
        assert result1.content == "[START]hello "

        # Second chunk (no prefix)
        chunk2 = ProcessedResponse(content="world")
        result2 = await feature.process(chunk2, "session1", context, is_streaming=True)
        assert result2.content == "world"

    @pytest.mark.asyncio
    async def test_streaming_applies_suffix_to_last_chunk(self):
        """Test that streaming applies suffix to last chunk."""
        feature = ContentTransformFeature(prefix="[START]", suffix="[END]")
        context: dict[str, Any] = {"is_done": True}

        # Final chunk
        chunk = ProcessedResponse(content="end")
        result = await feature.process(chunk, "session1", context, is_streaming=True)

        assert result.content == "[START]end[END]"

    @pytest.mark.asyncio
    async def test_streaming_equivalent_effect_to_non_streaming(self):
        """Test that streaming produces equivalent effect when combined."""
        feature = ContentTransformFeature(prefix="[", suffix="]")

        # Non-streaming: single response
        non_streaming_result = await feature.process(
            ProcessedResponse(content="AB"), "session1", {}, is_streaming=False
        )

        # Streaming: two chunks
        context: dict[str, Any] = {}
        chunk1 = await feature.process(
            ProcessedResponse(content="A"), "session1", context, is_streaming=True
        )
        context["is_done"] = True
        chunk2 = await feature.process(
            ProcessedResponse(content="B"), "session1", context, is_streaming=True
        )

        # Combined streaming result should equal non-streaming
        combined = chunk1.content + chunk2.content
        assert combined == non_streaming_result.content


class TestResponseLoggingFeature:
    """Tests for ResponseLoggingFeature demonstrating parity."""

    @pytest.mark.asyncio
    async def test_non_streaming_passes_through(self):
        """Test that non-streaming passes response through unchanged."""
        feature = ResponseLoggingFeature()
        response = ProcessedResponse(content="test", usage={"tokens": 100})

        result = await feature.process(response, "session1", {}, is_streaming=False)

        # Should return same object unchanged
        assert result is response

    @pytest.mark.asyncio
    async def test_streaming_passes_through(self):
        """Test that streaming passes chunk through unchanged."""
        feature = ResponseLoggingFeature()
        chunk = ProcessedResponse(content="chunk", usage={"tokens": 10})

        result = await feature.process(chunk, "session1", {}, is_streaming=True)

        # Should return same object unchanged
        assert result is chunk

    @pytest.mark.asyncio
    async def test_both_paths_have_equivalent_behavior(self):
        """Test that both paths produce equivalent results (pass-through)."""
        feature = ResponseLoggingFeature()
        response = ProcessedResponse(content="test")

        non_streaming = await feature.process(response, "s", {}, is_streaming=False)
        streaming = await feature.process(response, "s", {}, is_streaming=True)

        # Both should return the same object
        assert non_streaming is response
        assert streaming is response


class TestContentFilterFeature:
    """Tests for ContentFilterFeature demonstrating parity."""

    @pytest.mark.asyncio
    async def test_non_streaming_filters_prefix(self):
        """Test that non-streaming filters the configured prefix."""
        feature = ContentFilterFeature(filter_prefix="PREFIX: ")
        response = ProcessedResponse(content="PREFIX: actual content")

        result = await feature.process(response, "session1", {}, is_streaming=False)

        assert result.content == "actual content"

    @pytest.mark.asyncio
    async def test_non_streaming_no_filter_without_prefix(self):
        """Test that non-streaming passes through when no prefix."""
        feature = ContentFilterFeature(filter_prefix="PREFIX: ")
        response = ProcessedResponse(content="no prefix here")

        result = await feature.process(response, "session1", {}, is_streaming=False)

        assert result.content == "no prefix here"

    @pytest.mark.asyncio
    async def test_streaming_filters_prefix_first_chunk(self):
        """Test that streaming filters prefix only on first chunk."""
        feature = ContentFilterFeature(filter_prefix="HI: ")
        context: dict[str, Any] = {}

        # First chunk has prefix
        chunk1 = ProcessedResponse(content="HI: hello ")
        result1 = await feature.process(chunk1, "session1", context, is_streaming=True)
        assert result1.content == "hello "

        # Second chunk - prefix filtering shouldn't apply
        chunk2 = ProcessedResponse(content="HI: world")  # Even if content has prefix
        result2 = await feature.process(chunk2, "session1", context, is_streaming=True)
        # Second chunk passed through as-is (correct behavior for streaming)
        assert result2.content == "HI: world"

    @pytest.mark.asyncio
    async def test_parity_with_single_chunk_stream(self):
        """Test parity when streaming has single chunk."""
        feature = ContentFilterFeature(filter_prefix="X: ")

        response = ProcessedResponse(content="X: content")

        non_streaming = await feature.process(response, "s", {}, is_streaming=False)
        streaming = await feature.process(
            ProcessedResponse(content="X: content"), "s", {}, is_streaming=True
        )

        # Both should produce same result for single chunk
        assert non_streaming.content == streaming.content == "content"


class TestStreamingOnlyMetricsFeature:
    """Tests for StreamingOnlyMetricsFeature demonstrating capability declaration."""

    def test_capability_is_streaming_only(self):
        """Test that capability is declared as streaming only."""
        feature = StreamingOnlyMetricsFeature()
        assert feature.capability == FeatureCapability.STREAMING

    @pytest.mark.asyncio
    async def test_non_streaming_is_noop(self):
        """Test that non-streaming is explicitly a no-op."""
        feature = StreamingOnlyMetricsFeature()
        response = ProcessedResponse(content="test")

        result = await feature.process(response, "session1", {}, is_streaming=False)

        # Should return same object unchanged
        assert result is response

    @pytest.mark.asyncio
    async def test_streaming_tracks_metrics(self):
        """Test that streaming tracks chunk count."""
        feature = StreamingOnlyMetricsFeature()
        context: dict[str, Any] = {}

        # Process multiple chunks
        for i in range(3):
            chunk = ProcessedResponse(content=f"chunk{i}")
            await feature.process(chunk, "session1", context, is_streaming=True)

        # Verify metrics
        assert "streaming_metrics" in context
        assert context["streaming_metrics"]["chunk_count"] == 3


class TestParityVerification:
    """Meta-tests verifying the parity pattern works correctly."""

    @pytest.mark.asyncio
    async def test_transform_feature_maintains_invariant(self):
        """Test that transform feature's invariant holds:
        prefix + content + suffix = transformed content
        regardless of streaming/non-streaming path.
        """
        prefix = "["
        suffix = "]"
        content = "ABC"

        feature = ContentTransformFeature(prefix=prefix, suffix=suffix)

        # Non-streaming
        non_streaming = await feature.process(
            ProcessedResponse(content=content), "s", {}, is_streaming=False
        )

        # Streaming simulation (3 chunks: A, B, C)
        context: dict[str, Any] = {}
        results = []
        for i, char in enumerate(content):
            if i == len(content) - 1:
                context["is_done"] = True
            chunk = await feature.process(
                ProcessedResponse(content=char), "s", context, is_streaming=True
            )
            results.append(chunk.content)

        streaming_combined = "".join(results)

        # Both should equal: prefix + content + suffix
        expected = prefix + content + suffix
        assert non_streaming.content == expected
        assert streaming_combined == expected

    @pytest.mark.asyncio
    async def test_all_features_use_single_canonical_path(self):
        """Meta-test: verify example features expose process_chunk and process."""
        features = [
            ContentTransformFeature(),
            ResponseLoggingFeature(),
            ContentFilterFeature(),
            StreamingOnlyMetricsFeature(),
        ]

        for feature in features:
            assert callable(feature.process_chunk)
            assert callable(feature.process)

            response = ProcessedResponse(content="test")
            result1 = await feature.process(response, "s", {}, is_streaming=True)
            result2 = await feature.process(response, "s", {}, is_streaming=False)

            assert result1 is not None
            assert result2 is not None
