"""Unit tests for ReasoningMarkupProcessor service.

Tests cover reasoning markup tag processing: normalization, formatting, and extraction.

Requirements satisfied:
- Req 2.4: ReasoningMarkupProcessor extraction
- Req 11: Test-preserving migration
"""

import pytest
from src.connectors.hybrid_backend.models.reasoning_text import ReasoningText
from src.connectors.hybrid_backend.protocols import IReasoningMarkupProcessor


class TestReasoningMarkupProcessor:
    """Test ReasoningMarkupProcessor service implementation."""

    @pytest.fixture
    def processor(self):
        """Create a ReasoningMarkupProcessor instance for testing."""
        from src.connectors.hybrid_backend.services.reasoning_markup_processor import (
            ReasoningMarkupProcessor,
        )

        return ReasoningMarkupProcessor()

    def test_processor_implements_protocol(self, processor):
        """Verify processor implements IReasoningMarkupProcessor protocol."""
        assert isinstance(processor, IReasoningMarkupProcessor)

    def test_normalize_with_canonical_tags(self, processor):
        """Test normalize() with canonical tags."""
        reasoning_output = "<thinking>This is reasoning</thinking>"
        result = processor.normalize(reasoning_output, "openai")

        assert isinstance(result, ReasoningText)
        assert result.backend == "openai"
        assert "<think>" in result.tagged or "<thinking>" in result.tagged
        assert "This is reasoning" in result.plain

    def test_normalize_with_malformed_tags(self, processor):
        """Test normalize() with malformed/partial tags."""
        reasoning_output = "<thinking>Incomplete reasoning"
        result = processor.normalize(reasoning_output, "openai")

        assert isinstance(result, ReasoningText)
        # Should still normalize and close tags
        assert result.tagged
        assert "Incomplete reasoning" in result.plain

    def test_normalize_with_multiple_tag_variants(self, processor):
        """Test normalize() handles different tag variants."""
        reasoning_output = "<reason>Some reasoning</reason>"
        result = processor.normalize(reasoning_output, "anthropic")

        assert isinstance(result, ReasoningText)
        assert result.plain == "Some reasoning"

    def test_normalize_empty_input(self, processor):
        """Test normalize() with empty input."""
        result = processor.normalize("", "openai")

        assert isinstance(result, ReasoningText)
        assert result.tagged == ""
        assert result.plain == ""

    def test_format_for_model_backend_specific(self, processor):
        """Test format_for_model() selects backend-specific tags."""
        reasoning_output = "Some reasoning text"
        formatted = processor.format_for_model(reasoning_output, "openai")

        # Should use backend-specific tags
        assert formatted
        assert isinstance(formatted, str)

    def test_format_for_model_different_backends(self, processor):
        """Test format_for_model() uses different tags for different backends."""
        reasoning_output = "Some reasoning text"
        formatted_openai = processor.format_for_model(reasoning_output, "openai")
        formatted_anthropic = processor.format_for_model(reasoning_output, "anthropic")

        # Both should be formatted but may use different tags
        assert formatted_openai
        assert formatted_anthropic

    def test_extract_plain_text_strips_tags(self, processor):
        """Test extract_plain_text() strips all tags."""
        tagged_reasoning = "<think>This is the reasoning</think>"
        plain = processor.extract_plain_text(tagged_reasoning)

        assert plain == "This is the reasoning"
        assert "<think>" not in plain
        assert "</think>" not in plain

    def test_extract_plain_text_nested_tags(self, processor):
        """Test extract_plain_text() handles nested tags."""
        tagged_reasoning = "<thinking><b>Bold</b> reasoning</thinking>"
        plain = processor.extract_plain_text(tagged_reasoning)

        assert "<thinking>" not in plain
        assert "<b>" not in plain
        assert "</b>" not in plain
        assert "Bold" in plain
        assert "reasoning" in plain

    def test_extract_plain_text_empty(self, processor):
        """Test extract_plain_text() with empty input."""
        plain = processor.extract_plain_text("")

        assert plain == ""

    def test_extract_plain_text_no_tags(self, processor):
        """Test extract_plain_text() with text that has no tags."""
        plain = processor.extract_plain_text("Just plain text")

        assert plain == "Just plain text"

    def test_normalize_truncates_after_close_tag(self, processor):
        """Test normalize() truncates content after closing tag."""
        reasoning_output = "<thinking>Reasoning</thinking>Extra content after"
        result = processor.normalize(reasoning_output, "openai")

        assert "Extra content after" not in result.tagged
        assert "Extra content after" not in result.plain

    def test_normalize_handles_multiline_reasoning(self, processor):
        """Test normalize() handles multiline reasoning content."""
        reasoning_output = """<thinking>
        Line 1 of reasoning
        Line 2 of reasoning
        </thinking>"""
        result = processor.normalize(reasoning_output, "openai")

        assert "Line 1 of reasoning" in result.plain
        assert "Line 2 of reasoning" in result.plain

    def test_format_for_model_returns_empty_if_no_content(self, processor):
        """Test format_for_model() returns empty string if no reasoning content."""
        formatted = processor.format_for_model("", "openai")

        assert formatted == ""

    def test_normalize_preserves_backend_in_result(self, processor):
        """Test normalize() preserves backend name in ReasoningText."""
        reasoning_output = "<thinking>Test</thinking>"
        result = processor.normalize(reasoning_output, "custom-backend")

        assert result.backend == "custom-backend"
