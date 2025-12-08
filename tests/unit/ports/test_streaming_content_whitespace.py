"""Tests for whitespace preservation in StreamingContent.

This module contains critical regression tests for the bug where whitespace-only
streaming chunks (newlines, spaces, tabs) were incorrectly being dropped from
the streaming pipeline.

ORIGINAL BUG (Fixed 2025-12-08):
================================
In StreamingContent._compute_is_empty(), the condition:
    if self.content.strip():
        return False

Would incorrectly mark whitespace-only strings as "empty" because:
    "\n".strip() == ""  # empty string, which is falsy

This caused StreamNormalizer.process_stream() to skip these chunks:
    if content.is_empty and not content.is_done:
        continue

Symptoms observed:
- "Changes Made**Refactored sandboxing registration:**" (missing newline)
- "the tool call reactor factoryEnhanced streaming" (missing newline)
- "scenarios during cleanupUpdated tests:" (missing newline)

The fix changed the condition from `if self.content.strip():` to `if self.content:`
to ensure ANY non-empty string (including whitespace-only) is considered non-empty.

These tests are designed to catch any regression if this bug is re-introduced.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from src.core.ports.streaming_contracts import StreamingContent


class TestStreamingContentIsEmpty:
    """Test StreamingContent.is_empty behavior for various content types.

    CRITICAL: These tests verify that the `is_empty` property correctly
    identifies whitespace-only content as NON-EMPTY.
    """

    @pytest.mark.parametrize(
        "content,expected_is_empty",
        [
            # Empty string should be empty
            ("", True),
            # Whitespace-only strings should NOT be empty - THIS IS THE CRITICAL CASE
            ("\n", False),
            (" ", False),
            ("\t", False),
            ("  ", False),
            ("\n\n", False),
            ("\r\n", False),
            (" \n ", False),
            ("\t\n\t", False),
            # Non-whitespace should NOT be empty
            ("text", False),
            ("hello world", False),
            ("-", False),
            (".", False),
            ("*", False),
            ("**", False),
        ],
    )
    def test_is_empty_for_string_content(
        self, content: str, expected_is_empty: bool
    ) -> None:
        """Test that is_empty correctly identifies empty vs non-empty string content."""
        streaming_content = StreamingContent(content=content, metadata={})
        assert streaming_content.is_empty == expected_is_empty, (
            f"Expected is_empty={expected_is_empty} for content={content!r}, "
            f"got is_empty={streaming_content.is_empty}"
        )

    def test_newline_chunk_not_filtered(self) -> None:
        """Test that a newline-only chunk is not considered empty.

        REGRESSION TEST for the bug where whitespace-only chunks were dropped
        because is_empty used content.strip() to check for emptiness.
        """
        newline_chunk = StreamingContent(
            content="\n",
            metadata={"session_id": "test"},
            is_done=False,
        )

        # This chunk should NOT be empty
        assert (
            not newline_chunk.is_empty
        ), "Newline-only chunk should not be considered empty"

        # The chunk should be serializable to SSE bytes
        sse_bytes = newline_chunk.to_bytes()
        assert b"\\n" in sse_bytes, "Newline should be preserved in SSE serialization"

    def test_space_chunk_not_filtered(self) -> None:
        """Test that a space-only chunk is not considered empty.

        Spaces between words must be preserved during streaming.
        """
        space_chunk = StreamingContent(
            content=" ",
            metadata={"session_id": "test"},
            is_done=False,
        )

        assert (
            not space_chunk.is_empty
        ), "Space-only chunk should not be considered empty"

    def test_dict_content_not_affected(self) -> None:
        """Test that dict content is never considered empty.

        Dict content (like OpenAI-style chunks) should always be non-empty.
        """
        dict_chunk = StreamingContent(
            content={"choices": [{"delta": {"content": "\n"}}]},
            metadata={},
            is_done=False,
        )

        assert not dict_chunk.is_empty, "Dict content should never be considered empty"

    def test_empty_string_is_empty(self) -> None:
        """Test that truly empty strings are correctly identified as empty."""
        empty_chunk = StreamingContent(
            content="",
            metadata={},
            is_done=False,
        )

        assert empty_chunk.is_empty, "Empty string should be considered empty"


class TestStreamingContentFromRaw:
    """Test StreamingContent.from_raw() correctly handles whitespace content."""

    def test_from_raw_preserves_newline_in_delta(self) -> None:
        """Test that from_raw extracts and preserves newline content from OpenAI delta."""
        raw_chunk = {
            "choices": [
                {
                    "delta": {"role": "assistant", "content": "\n"},
                    "finish_reason": None,
                }
            ],
            "id": "test-123",
            "model": "test-model",
            "created": 12345,
        }

        streaming_content = StreamingContent.from_raw(raw_chunk)

        # The content should be the newline (extracted from delta)
        assert (
            streaming_content.content == "\n"
        ), f"Expected content='\\n', got {streaming_content.content!r}"

        # Should NOT be empty
        assert (
            not streaming_content.is_empty
        ), "Newline chunk from OpenAI delta should not be empty"

    def test_from_raw_preserves_space_in_delta(self) -> None:
        """Test that from_raw extracts and preserves space content from OpenAI delta."""
        raw_chunk = {
            "choices": [
                {
                    "delta": {"role": "assistant", "content": " "},
                    "finish_reason": None,
                }
            ],
            "id": "test-123",
            "model": "test-model",
            "created": 12345,
        }

        streaming_content = StreamingContent.from_raw(raw_chunk)

        # The content should be the space (extracted from delta)
        assert (
            streaming_content.content == " "
        ), f"Expected content=' ', got {streaming_content.content!r}"

        # Should NOT be empty
        assert (
            not streaming_content.is_empty
        ), "Space chunk from OpenAI delta should not be empty"

    def test_from_raw_sse_bytes_preserves_newline(self) -> None:
        """Test that from_raw handles SSE bytes with newline content."""
        sse_bytes = (
            b'data: {"choices": [{"delta": {"content": "\\n"}}], "id": "test"}\n\n'
        )

        streaming_content = StreamingContent.from_raw(sse_bytes)

        # After parsing, the content should be the newline
        assert (
            streaming_content.content == "\n"
        ), f"Expected content='\\n', got {streaming_content.content!r}"
        assert not streaming_content.is_empty


class TestComputeIsEmptyRegression:
    """Direct tests for the _compute_is_empty method regression.

    These tests specifically verify the bug fix in _compute_is_empty() where
    whitespace-only strings were incorrectly marked as empty.
    """

    def test_compute_is_empty_newline_string(self) -> None:
        """CRITICAL: Newline-only string must NOT be considered empty.

        This was the exact bug: _compute_is_empty() used self.content.strip()
        which turned "\\n" into "" (falsy), causing the chunk to be skipped.
        """
        chunk = StreamingContent(content="\n", metadata={})

        # Access the computed is_empty property
        is_empty = chunk.is_empty

        assert is_empty is False, (
            "REGRESSION: Newline-only string is being considered empty! "
            "This causes whitespace to be dropped from streaming output."
        )

    def test_compute_is_empty_various_whitespace(self) -> None:
        """Verify all whitespace types are NOT considered empty."""
        whitespace_variants = [
            "\n",  # Unix newline
            "\r\n",  # Windows newline
            "\r",  # Carriage return
            " ",  # Single space
            "  ",  # Multiple spaces
            "\t",  # Tab
            "\t\t",  # Multiple tabs
            " \n",  # Space + newline
            "\n ",  # Newline + space
            " \t\n",  # Mixed whitespace
        ]

        for ws in whitespace_variants:
            chunk = StreamingContent(content=ws, metadata={})
            assert not chunk.is_empty, (
                f"REGRESSION: Whitespace {ws!r} is being considered empty! "
                f"This will cause text formatting issues in streaming output."
            )

    def test_compute_is_empty_only_truly_empty_is_empty(self) -> None:
        """Only truly empty string should be marked as empty."""
        # These SHOULD be empty
        empty_cases = [""]

        # These should NOT be empty (they contain characters, even if whitespace)
        non_empty_cases = ["\n", " ", "\t", "a", "-", ".", " a ", "\n\n"]

        for content in empty_cases:
            chunk = StreamingContent(content=content, metadata={})
            assert chunk.is_empty, f"Content {content!r} should be empty"

        for content in non_empty_cases:
            chunk = StreamingContent(content=content, metadata={})
            assert not chunk.is_empty, f"Content {content!r} should NOT be empty"


class TestStreamNormalizerWhitespaceHandling:
    """Test that StreamNormalizer correctly passes through whitespace chunks.

    These tests verify the integration between StreamingContent.is_empty
    and StreamNormalizer.process_stream() to ensure whitespace is preserved.
    """

    @pytest.mark.asyncio
    async def test_normalizer_preserves_newline_chunks(self) -> None:
        """Test that StreamNormalizer yields newline chunks, not skips them."""
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Simulate a stream with newline chunks interspersed
        chunks = [
            {"choices": [{"delta": {"content": "Hello"}}], "id": "1"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "2"},  # Newline chunk
            {"choices": [{"delta": {"content": "World"}}], "id": "3"},
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        results: list[bytes] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="bytes"
        ):
            if isinstance(output, bytes):
                results.append(output)

        # Should have exactly 3 chunks (Hello, newline, World)
        assert len(results) == 3, (
            f"Expected 3 chunks but got {len(results)}. "
            f"REGRESSION: Whitespace chunks may be getting filtered out!"
        )

        # Verify the newline is present in the output
        all_content = b"".join(results)
        assert b"\\n" in all_content, (
            "REGRESSION: Newline content is missing from output! "
            "StreamNormalizer is filtering out whitespace chunks."
        )

    @pytest.mark.asyncio
    async def test_normalizer_preserves_space_between_words(self) -> None:
        """Test that space chunks between words are preserved."""
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Simulate streaming "hello world" with space as separate chunk
        chunks = [
            {"choices": [{"delta": {"content": "hello"}}], "id": "1"},
            {"choices": [{"delta": {"content": " "}}], "id": "2"},  # Space chunk
            {"choices": [{"delta": {"content": "world"}}], "id": "3"},
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        results: list[bytes] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="bytes"
        ):
            if isinstance(output, bytes):
                results.append(output)

        assert len(results) == 3, (
            f"Expected 3 chunks but got {len(results)}. "
            f"REGRESSION: Space chunk between words was filtered out!"
        )

    @pytest.mark.asyncio
    async def test_normalizer_preserves_multiple_newlines(self) -> None:
        """Test that multiple consecutive newlines are preserved."""
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Simulate a markdown paragraph break (double newline)
        chunks = [
            {"choices": [{"delta": {"content": "First paragraph."}}], "id": "1"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "2"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "3"},  # Second newline
            {"choices": [{"delta": {"content": "Second paragraph."}}], "id": "4"},
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        results: list[bytes] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="bytes"
        ):
            if isinstance(output, bytes):
                results.append(output)

        assert len(results) == 4, (
            f"Expected 4 chunks but got {len(results)}. "
            f"REGRESSION: Consecutive newline chunks were filtered out!"
        )


class TestExactCBORCaptureScenario:
    """Tests based on the exact CBOR capture that revealed the bug.

    From CBOR entry 1219-1221:
    - B->P: {"choices": [{"delta": {"content": "\\n"}}], ...}  (timestamp X)
    - B->P: {"choices": [{"delta": {"content": "-"}}], ...}   (timestamp X)
    - P->C: {"choices": [{"delta": {"content": "-"}}], ...}   (timestamp X)
                                                               ^ newline was DROPPED!

    This simulates the exact scenario that caused the bug.
    """

    @pytest.mark.asyncio
    async def test_rapid_successive_chunks_preserve_whitespace(self) -> None:
        """Test that rapid successive chunks don't lose whitespace.

        In the original bug, chunks arriving at the same millisecond
        (within the same processing batch) could have whitespace dropped.
        """
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Exact scenario from CBOR capture
        rapid_chunks = [
            {
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "\n"},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-1765213513-eNSJ347VpQI4YVBtRgOj",
                "model": "x-ai/grok-code-fast-1",
                "created": 1765213513,
            },
            {
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "-"},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-1765213513-eNSJ347VpQI4YVBtRgOj",
                "model": "x-ai/grok-code-fast-1",
                "created": 1765213513,
            },
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in rapid_chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        results: list[bytes] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="bytes"
        ):
            if isinstance(output, bytes):
                results.append(output)

        # CRITICAL: Both chunks must be yielded
        assert len(results) == 2, (
            f"Expected 2 chunks (newline + dash) but got {len(results)}. "
            f"REGRESSION: The newline chunk is being dropped!"
        )

        # Verify the newline is in the first chunk
        first_chunk_str = results[0].decode("utf-8")
        assert (
            "\\n" in first_chunk_str
        ), f"First chunk should contain newline but got: {first_chunk_str}"

        # Verify the dash is in the second chunk
        second_chunk_str = results[1].decode("utf-8")
        assert (
            '"-"' in second_chunk_str or 'content": "-"' in second_chunk_str
        ), f"Second chunk should contain dash but got: {second_chunk_str}"

    def test_streaming_content_from_cbor_scenario(self) -> None:
        """Test StreamingContent creation from exact CBOR data."""
        # The exact chunk that was being dropped
        cbor_newline_chunk = {
            "choices": [
                {
                    "delta": {"role": "assistant", "content": "\n"},
                    "finish_reason": None,
                }
            ],
            "id": "gen-1765213513-eNSJ347VpQI4YVBtRgOj",
            "model": "x-ai/grok-code-fast-1",
            "created": 1765213513,
        }

        content = StreamingContent.from_raw(cbor_newline_chunk)

        # Must NOT be empty
        assert not content.is_empty, (
            "CRITICAL REGRESSION: The exact CBOR chunk that caused the bug "
            "is still being marked as empty!"
        )

        # Content must be the newline
        assert (
            content.content == "\n"
        ), f"Content should be newline but got {content.content!r}"


class TestTextFormattingPreservation:
    """Tests that verify proper text formatting is preserved during streaming.

    These tests simulate real-world scenarios where whitespace is critical
    for proper text rendering.
    """

    @pytest.mark.asyncio
    async def test_markdown_bullet_list_formatting(self) -> None:
        """Test that markdown bullet lists maintain proper formatting.

        Original bug symptom:
        "Changes Made**Refactored sandboxing registration:**"
        Should be:
        "Changes Made\n\n**Refactored sandboxing registration:**"
        """
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        # Simulate streaming: "Changes Made" + newlines + "**Refactored"
        chunks = [
            {"choices": [{"delta": {"content": "Changes Made"}}], "id": "1"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "2"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "3"},
            {"choices": [{"delta": {"content": "**Refactored"}}], "id": "4"},
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        contents: list[str] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            if isinstance(output, StreamingContent) and output.content:
                if isinstance(output.content, str):
                    contents.append(output.content)
                elif isinstance(output.content, dict):
                    # Extract content from dict if needed
                    delta = output.content.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta:
                        contents.append(delta["content"])

        combined = "".join(contents)
        assert combined == "Changes Made\n\n**Refactored", (
            f"Expected 'Changes Made\\n\\n**Refactored' but got {combined!r}. "
            f"REGRESSION: Newlines between sections are being dropped!"
        )

    @pytest.mark.asyncio
    async def test_sentence_spacing_preserved(self) -> None:
        """Test that spaces between sentences are preserved.

        Original bug symptom:
        "the tool call reactor factoryEnhanced streaming"
        Should have newline between "factory" and "Enhanced"
        """
        from src.core.services.streaming.stream_normalizer import StreamNormalizer

        chunks = [
            {"choices": [{"delta": {"content": "factory"}}], "id": "1"},
            {"choices": [{"delta": {"content": "\n"}}], "id": "2"},
            {"choices": [{"delta": {"content": "Enhanced"}}], "id": "3"},
        ]

        async def mock_stream() -> AsyncIterator[dict[str, Any]]:
            for chunk in chunks:
                yield chunk

        normalizer = StreamNormalizer(processors=[])
        contents: list[str] = []

        async for output in normalizer.process_stream(
            mock_stream(), output_format="objects"
        ):
            if isinstance(output, StreamingContent) and output.content:
                if isinstance(output.content, str):
                    contents.append(output.content)
                elif isinstance(output.content, dict):
                    delta = output.content.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta:
                        contents.append(delta["content"])

        combined = "".join(contents)
        assert combined == "factory\nEnhanced", (
            f"Expected 'factory\\nEnhanced' but got {combined!r}. "
            f"REGRESSION: Newline between words is being dropped!"
        )


class TestSSESerializationPreservesWhitespace:
    """Test that SSE serialization (to_bytes) preserves whitespace content."""

    def test_to_bytes_preserves_newline_in_string_content(self) -> None:
        """Test that to_bytes correctly serializes newline string content."""
        chunk = StreamingContent(content="\n", metadata={"session_id": "test"})
        sse_bytes = chunk.to_bytes()

        # The SSE bytes should contain the escaped newline
        assert (
            b"\\n" in sse_bytes
        ), f"SSE bytes should contain escaped newline but got: {sse_bytes}"

    def test_to_bytes_preserves_space_in_string_content(self) -> None:
        """Test that to_bytes correctly serializes space string content."""
        chunk = StreamingContent(content=" ", metadata={"session_id": "test"})
        sse_bytes = chunk.to_bytes()

        # Parse the SSE to verify space is present
        sse_str = sse_bytes.decode("utf-8")
        assert "data:" in sse_str

        # Extract the JSON payload
        for line in sse_str.split("\n"):
            if line.startswith("data:"):
                json_str = line[5:].strip()
                if json_str and json_str != "[DONE]":
                    payload = json.loads(json_str)
                    # Find the content in the payload
                    if "choices" in payload:
                        delta = payload["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        assert (
                            content == " "
                        ), f"Expected space content but got {content!r}"

    def test_to_bytes_preserves_various_whitespace(self) -> None:
        """Test that to_bytes handles various whitespace types."""
        whitespace_cases = ["\n", " ", "\t", "\r\n", "  ", "\n\n"]

        for ws in whitespace_cases:
            chunk = StreamingContent(content=ws, metadata={})
            sse_bytes = chunk.to_bytes()

            # Should produce valid SSE bytes
            assert sse_bytes, f"to_bytes() returned empty for whitespace {ws!r}"

            # Should be decodable
            sse_str = sse_bytes.decode("utf-8")
            assert "data:" in sse_str, f"Missing 'data:' prefix for whitespace {ws!r}"


class TestEdgeCasesWhitespace:
    """Edge cases for whitespace handling."""

    def test_none_content_raises_validation_error(self) -> None:
        """Test that None content raises validation error (not allowed)."""
        with pytest.raises(ValueError, match="content must be str, dict, or bytes"):
            StreamingContent(content=None, metadata={})

    def test_dict_with_empty_content_not_empty(self) -> None:
        """Test that dict content is never empty, even with empty string inside."""
        chunk = StreamingContent(
            content={"choices": [{"delta": {"content": ""}}]},
            metadata={},
        )
        # Dict content itself is not empty (the dict exists)
        assert not chunk.is_empty

    def test_dict_with_whitespace_content_not_empty(self) -> None:
        """Test that dict content with whitespace is not empty."""
        chunk = StreamingContent(
            content={"choices": [{"delta": {"content": "\n"}}]},
            metadata={},
        )
        assert not chunk.is_empty

    def test_is_done_chunk_not_filtered_even_if_empty(self) -> None:
        """Test that is_done chunks are never filtered, even if content is empty."""
        done_chunk = StreamingContent(
            content="",  # Empty content
            metadata={},
            is_done=True,  # But marked as done
        )

        # is_empty should be True (content is empty)
        assert done_chunk.is_empty

        # But the StreamNormalizer should still yield it because is_done=True
        # (The skip condition is: if content.is_empty and not content.is_done)
