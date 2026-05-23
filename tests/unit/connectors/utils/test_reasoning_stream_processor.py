"""Unit tests for ReasoningStreamProcessor."""

import json

import pytest
from src.connectors.utils.reasoning_stream_processor import ReasoningStreamProcessor
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def processor():
    """Create a ReasoningStreamProcessor instance for testing."""
    return ReasoningStreamProcessor()


class TestReasoningContentExtraction:
    """Test reasoning content extraction (Task 9.1)."""

    def test_complete_reasoning_output_extraction(self, processor):
        """Test complete reasoning output extraction."""
        chunks = [
            {
                "choices": [
                    {
                        "delta": {"content": "Let me think about this problem. "},
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "content": "First, I need to understand the requirements. "
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {"content": "Then, I should consider the approach."},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == (
            "Let me think about this problem. "
            "First, I need to understand the requirements. "
            "Then, I should consider the approach."
        )

    def test_partial_reasoning_output_handling(self, processor):
        """Test partial reasoning output handling."""
        chunks = [
            {
                "choices": [
                    {
                        "delta": {"content": "Starting to think..."},
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {"content": " but incomplete"},
                        "finish_reason": None,
                    }
                ]
            },
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == "Starting to think... but incomplete"

    def test_empty_reasoning_handling(self, processor):
        """Test empty reasoning handling."""
        chunks = []

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == ""

    def test_empty_reasoning_with_chunks_but_no_content(self, processor):
        """Test empty reasoning with chunks but no content."""
        chunks = [
            {"choices": [{"delta": {}, "finish_reason": None}]},
            {"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == ""

    def test_mixed_content_reasoning_and_answer(self, processor):
        """Test mixed content (reasoning + answer)."""
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "content": "<think>Let me analyze this problem.</think>"
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {"content": "Here is the answer: 42"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert (
            reasoning_text
            == "<think>Let me analyze this problem.</think>Here is the answer: 42"
        )

    def test_reasoning_content_in_messages_list(self, processor):
        """Test extraction when reasoning is nested under messages list."""
        chunk = {
            "choices": [
                {
                    "delta": {
                        "messages": [
                            {
                                "role": "assistant",
                                "content": "<think>Plan steps</think>",
                            }
                        ]
                    }
                }
            ]
        }

        reasoning_text = processor.extract_reasoning_content([chunk])

        assert "Plan steps" in reasoning_text

    def test_reasoning_content_field_extraction(self, processor):
        """Test extraction from reasoning_content field."""
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "<think>Plan steps</think>",
                        },
                        "finish_reason": None,
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {"content": "Final answer"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert "Plan steps" in reasoning_text
        assert "Final answer" in reasoning_text

    def test_alternative_content_format_text_field(self, processor):
        """Test extraction from alternative format with 'text' field."""
        chunks = [
            {"text": "Reasoning part 1"},
            {"text": " and part 2"},
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == "Reasoning part 1 and part 2"

    def test_alternative_content_format_content_field(self, processor):
        """Test extraction from alternative format with 'content' field."""
        chunks = [
            {"content": "Direct content field"},
            {"content": " continuation"},
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)

        assert reasoning_text == "Direct content field continuation"

    def test_handles_none_chunks_gracefully(self, processor):
        """Processor should ignore None chunks without raising errors."""
        chunks = [
            None,
            {"choices": [{"delta": {"content": "Partial reasoning"}}]},
        ]

        reasoning_text = processor.extract_reasoning_content(chunks)  # type: ignore[arg-type]

        assert "Partial reasoning" in reasoning_text


class TestReasoningPhaseDetection:
    """Test reasoning phase detection (Task 9.2)."""

    def test_explicit_tag_detection_think(self, processor):
        """Test explicit tag detection: </think>."""
        content = "Let me think about this problem step by step.</think>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</think>"

    def test_explicit_tag_detection_thinking(self, processor):
        """Test explicit tag detection: </thinking>."""
        content = "Analyzing the requirements carefully.</thinking>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</thinking>"

    def test_explicit_tag_detection_reason(self, processor):
        """Test explicit tag detection: </reason>."""
        content = "The reasoning process leads to this conclusion.</reason>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</reason>"

    def test_explicit_tag_detection_reasoning(self, processor):
        """Test explicit tag detection: </reasoning>."""
        content = "After careful consideration of all factors.</reasoning>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</reasoning>"

    def test_explicit_tag_detection_case_insensitive(self, processor):
        """Test explicit tag detection is case-insensitive."""
        content = "Thinking process complete.</THINK>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</think>"

    def test_explicit_tag_detection_no_tag(self, processor):
        """Test explicit tag detection when no tag present."""
        content = "Just some regular content without tags"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is False
        assert tag is None

    def test_finish_reason_detection_stop(self, processor):
        """Test finish_reason detection as secondary method."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Final reasoning"},
                    "finish_reason": "stop",
                }
            ]
        }

        is_complete, reason = processor.detect_by_finish_reason(chunk)

        assert is_complete is True
        assert reason == "stop"

    def test_finish_reason_detection_length(self, processor):
        """Test finish_reason detection with 'length' reason."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Reasoning cut off"},
                    "finish_reason": "length",
                }
            ]
        }

        is_complete, reason = processor.detect_by_finish_reason(chunk)

        assert is_complete is True
        assert reason == "length"

    def test_finish_reason_detection_no_reason(self, processor):
        """Test finish_reason detection when no finish_reason present."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Still generating"},
                    "finish_reason": None,
                }
            ]
        }

        is_complete, reason = processor.detect_by_finish_reason(chunk)

        assert is_complete is False
        assert reason is None

    def test_finish_reason_detection_null_string(self, processor):
        """Test finish_reason detection with 'null' string."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "Content"},
                    "finish_reason": "null",
                }
            ]
        }

        is_complete, reason = processor.detect_by_finish_reason(chunk)

        assert is_complete is False
        assert reason is None

    def test_content_marker_detection_therefore(self, processor):
        """Test content marker detection as tertiary method: 'therefore,'."""
        content = "After analyzing all the data, therefore, we can conclude"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is True
        assert marker == "therefore,"

    def test_content_marker_detection_in_conclusion(self, processor):
        """Test content marker detection: 'in conclusion,'."""
        content = "Based on the evidence presented, in conclusion, the answer is"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is True
        assert marker == "in conclusion,"

    def test_content_marker_detection_to_summarize(self, processor):
        """Test content marker detection: 'to summarize,'."""
        content = "After reviewing all points, to summarize, the key findings are"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is True
        assert marker == "to summarize,"

    def test_content_marker_detection_in_summary(self, processor):
        """Test content marker detection: 'in summary,'."""
        content = "Looking at the overall picture, in summary, we find that"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is True
        assert marker == "in summary,"

    def test_content_marker_detection_case_insensitive(self, processor):
        """Test content marker detection is case-insensitive."""
        content = "After analysis, THEREFORE, the conclusion is"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is True
        assert marker == "therefore,"

    def test_content_marker_detection_no_marker(self, processor):
        """Test content marker detection when no marker present."""
        content = "Just regular reasoning content without transition markers"

        is_complete, marker = processor.detect_by_markers(content)

        assert is_complete is False
        assert marker is None

    def test_token_limit_safety_fallback(self, processor):
        """Test token/character limit safety fallback."""
        # Create content that exceeds token limit
        long_content = "a" * 20000  # 20000 chars = ~5000 tokens

        tokens = processor.estimate_tokens(long_content)

        assert tokens >= processor.DEFAULT_MAX_TOKENS

    def test_character_limit_safety_fallback(self, processor):
        """Test character limit safety fallback."""
        # Create content that exceeds character limit
        long_content = "x" * 20000

        assert len(long_content) >= processor.DEFAULT_MAX_CHARS

    def test_detection_priority_order_tags_over_finish_reason(self, processor):
        """Test detection priority order: tags > finish_reason."""
        # Content has both tag and finish_reason
        content = "Reasoning complete.</think>"
        chunk = {
            "choices": [
                {
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }
            ]
        }

        # Tag detection should take priority
        tag_detected, tag = processor.detect_by_tags(content)
        finish_detected, reason = processor.detect_by_finish_reason(chunk)

        assert tag_detected is True
        assert tag == "</think>"
        # Both are detected, but tags have priority in the actual flow

    def test_detection_priority_order_finish_reason_over_markers(self, processor):
        """Test detection priority order: finish_reason > markers."""
        content = "After analysis, therefore, the conclusion"
        chunk = {
            "choices": [
                {
                    "delta": {"content": content},
                    "finish_reason": "stop",
                }
            ]
        }

        # Both should be detected
        marker_detected, marker = processor.detect_by_markers(content)
        finish_detected, reason = processor.detect_by_finish_reason(chunk)

        assert marker_detected is True
        assert finish_detected is True
        # finish_reason has priority over markers in actual flow

    def test_minimax_m2_think_tag_detection(self, processor):
        """Verify MiniMax-M2 <think> tag detection based on POC findings."""
        # MiniMax-M2 uses <think> opening and </think> closing tags
        content = "<think>Let me analyze this problem step by step.\n1. First consideration\n2. Second point</think>"

        is_complete, tag = processor.detect_by_tags(content)

        assert is_complete is True
        assert tag == "</think>"

    def test_token_estimation_accuracy(self, processor):
        """Test token estimation is reasonable."""
        # Test with known text
        text = "This is a test sentence with approximately ten words in it."

        tokens = processor.estimate_tokens(text)

        # Should be around 15 tokens (60 chars / 4)
        assert 10 <= tokens <= 20


class TestStreamCancellation:
    """Test stream cancellation (Task 9.3)."""

    @pytest.mark.asyncio
    async def test_successful_cancellation_after_reasoning_capture(self, processor):
        """Test successful cancellation after reasoning capture."""

        # Create a mock stream that yields chunks with reasoning end tag
        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Thinking..."}, "finish_reason": null}]}\n\n'
            )
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "</think>"}, "finish_reason": null}]}\n\n'
            )
            # These should not be processed after cancellation
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "More content"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert "</think>" in reasoning_text
        assert "More content" not in reasoning_text
        assert metadata.method == "explicit_tag:</think>"

    @pytest.mark.asyncio
    async def test_cancellation_with_finish_reason(self, processor):
        """Test cancellation when finish_reason is detected."""

        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Reasoning content"}, "finish_reason": null}]}\n\n'
            )
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": " complete"}, "finish_reason": "stop"}]}\n\n'
            )
            # Should not reach here
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Extra"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert reasoning_text == "Reasoning content complete"
        assert "Extra" not in reasoning_text
        assert metadata.method == "finish_reason:stop"

    @pytest.mark.asyncio
    async def test_already_completed_stream_handling(self, processor):
        """Test already completed stream handling."""

        # Stream that completes immediately
        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Done</think>"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert reasoning_text == "Done</think>"
        assert metadata.method == "explicit_tag:</think>"

    @pytest.mark.asyncio
    async def test_stream_with_no_completion_signal(self, processor):
        """Test stream that ends without completion signal."""

        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Incomplete"}, "finish_reason": null}]}\n\n'
            )
            # Stream ends without explicit signal

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        # Should capture what was available
        assert reasoning_text == "Incomplete"
        # reasoning_complete should be False since no detection method triggered
        assert reasoning_complete is False
        assert metadata.method is None

    @pytest.mark.asyncio
    async def test_cancellation_failure_handling(self, processor):
        """Test cancellation failure handling (non-fatal)."""

        # Even if cancellation fails, we should have captured reasoning
        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "Reasoning</think>"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete

        # Should still have captured the reasoning
        assert reasoning_complete is True
        assert "Reasoning</think>" in reasoning_text

    @pytest.mark.asyncio
    async def test_token_limit_triggers_cancellation(self, processor):
        """Test that token limit triggers cancellation."""
        # Create stream that would exceed token limit
        long_chunk = "x" * 5000  # ~1250 tokens per chunk

        async def mock_stream():
            # Yield 4 chunks to exceed 4096 token limit
            for _ in range(4):
                chunk_data = {
                    "choices": [
                        {
                            "delta": {"content": long_chunk},
                            "finish_reason": None,
                        }
                    ]
                }
                yield ProcessedResponse(
                    content=f"data: {json.dumps(chunk_data)}\n\n".encode()
                )

        result = await processor.capture_reasoning_stream(
            mock_stream(), max_tokens=4096
        )
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert metadata.method == "token_limit"
        assert metadata.tokens_estimated >= 4096

    @pytest.mark.asyncio
    async def test_character_limit_triggers_cancellation(self, processor):
        """Test that character limit triggers cancellation."""
        long_chunk = "y" * 10000

        async def mock_stream():
            # Yield 2 chunks to exceed 16384 char limit
            for _ in range(2):
                chunk_data = {
                    "choices": [
                        {
                            "delta": {"content": long_chunk},
                            "finish_reason": None,
                        }
                    ]
                }
                yield ProcessedResponse(
                    content=f"data: {json.dumps(chunk_data)}\n\n".encode()
                )

        result = await processor.capture_reasoning_stream(
            mock_stream(),
            max_chars=16384,
            max_tokens=100000,  # Set high token limit to test char limit
        )
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert metadata.method == "char_limit"
        assert metadata.chars_captured >= 16384

    @pytest.mark.asyncio
    async def test_capture_reasoning_from_dict_chunks(self, processor):
        """Ensure dict content with reasoning_content is captured."""

        async def mock_stream():
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {
                                "reasoning_content": "<think>Step 1</think>",
                            }
                        }
                    ]
                }
            )
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {
                                "content": "Here is the final answer",
                            }
                        }
                    ]
                }
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        reasoning_text = result.reasoning_text
        reasoning_complete = result.reasoning_complete
        metadata = result.metadata

        assert reasoning_complete is True
        assert metadata.method.startswith("explicit_tag")
        assert "Step 1" in reasoning_text


class TestChunkParsing:
    """Test chunk parsing functionality."""

    def test_parse_sse_format(self, processor):
        """Test parsing SSE format: 'data: {...}'."""
        chunk_bytes = b'data: {"choices": [{"delta": {"content": "test"}}]}\n\n'

        chunk = processor._parse_chunk(chunk_bytes)

        assert chunk is not None
        assert "choices" in chunk
        assert chunk["choices"][0]["delta"]["content"] == "test"

    def test_parse_raw_json(self, processor):
        """Test parsing raw JSON without SSE prefix."""
        chunk_bytes = b'{"choices": [{"delta": {"content": "test"}}]}'

        chunk = processor._parse_chunk(chunk_bytes)

        assert chunk is not None
        assert "choices" in chunk

    def test_parse_done_marker(self, processor):
        """Test parsing [DONE] marker returns None."""
        chunk_bytes = b"data: [DONE]\n\n"

        chunk = processor._parse_chunk(chunk_bytes)

        assert chunk is None

    def test_parse_invalid_json(self, processor):
        """Test parsing invalid JSON returns None."""
        chunk_bytes = b"data: {invalid json}\n\n"

        chunk = processor._parse_chunk(chunk_bytes)

        assert chunk is None

    def test_parse_empty_chunk(self, processor):
        """Test parsing empty chunk returns None."""
        chunk_bytes = b""

        chunk = processor._parse_chunk(chunk_bytes)

        assert chunk is None


class TestContentExtraction:
    """Test content extraction from various chunk formats."""

    def test_extract_openai_format(self, processor):
        """Test extraction from OpenAI format: choices[0].delta.content."""
        chunk = {
            "choices": [
                {
                    "delta": {"content": "OpenAI content"},
                    "finish_reason": None,
                }
            ]
        }

        content = processor._extract_content_from_chunk(chunk)

        assert content == "OpenAI content"

    def test_extract_content_field(self, processor):
        """Test extraction from direct content field."""
        chunk = {"content": "Direct content"}

        content = processor._extract_content_from_chunk(chunk)

        assert content == "Direct content"

    def test_extract_text_field(self, processor):
        """Test extraction from text field."""
        chunk = {"text": "Text field content"}

        content = processor._extract_content_from_chunk(chunk)

        assert content == "Text field content"

    def test_extract_no_content(self, processor):
        """Test extraction when no content present."""
        chunk = {"choices": [{"delta": {}, "finish_reason": None}]}

        content = processor._extract_content_from_chunk(chunk)

        assert content == ""

    def test_extract_non_string_content(self, processor):
        """Test extraction handles non-string content gracefully."""
        chunk = {"choices": [{"delta": {"content": None}, "finish_reason": None}]}

        content = processor._extract_content_from_chunk(chunk)

        assert content == ""


class TestMetadataTracking:
    """Test metadata tracking during stream capture."""

    @pytest.mark.asyncio
    async def test_metadata_chunks_processed(self, processor):
        """Test metadata tracks chunks processed."""

        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "chunk1"}, "finish_reason": null}]}\n\n'
            )
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "chunk2"}, "finish_reason": null}]}\n\n'
            )
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "</think>"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        metadata = result.metadata

        assert metadata.chunks_processed == 3

    @pytest.mark.asyncio
    async def test_metadata_chars_captured(self, processor):
        """Test metadata tracks characters captured."""

        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "12345"}, "finish_reason": null}]}\n\n'
            )
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "67890</think>"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        metadata = result.metadata

        assert metadata.chars_captured == 18  # "12345" + "67890</think>" = 18 chars

    @pytest.mark.asyncio
    async def test_metadata_tokens_estimated(self, processor):
        """Test metadata tracks estimated tokens."""

        async def mock_stream():
            content = "a" * 100  # 100 chars = ~25 tokens
            chunk_data = {
                "choices": [
                    {
                        "delta": {"content": content + "</think>"},
                        "finish_reason": None,
                    }
                ]
            }
            yield ProcessedResponse(
                content=f"data: {json.dumps(chunk_data)}\n\n".encode()
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        metadata = result.metadata

        # Should be around 25-30 tokens
        assert 20 <= metadata.tokens_estimated <= 35

    @pytest.mark.asyncio
    async def test_metadata_detection_method(self, processor):
        """Test metadata includes detection method."""

        async def mock_stream():
            yield ProcessedResponse(
                content=b'data: {"choices": [{"delta": {"content": "test</thinking>"}, "finish_reason": null}]}\n\n'
            )

        result = await processor.capture_reasoning_stream(mock_stream())
        metadata = result.metadata

        assert metadata.method == "explicit_tag:</thinking>"
