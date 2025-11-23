"""
Contract tests for Gemini stream normalizer.

These tests verify that the Gemini normalizer correctly handles all
Gemini-specific chunk formats and maps metadata completely.

Feature: streaming-pipeline-refactor
Requirements: 8.2, 8.3
"""

import json

import pytest
from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
from src.core.ports.streaming_contracts import SentinelManager, StreamingContent


class TestGeminiStreamNormalizerContract:
    """Contract tests for Gemini normalizer."""

    @pytest.fixture
    def normalizer(self) -> GeminiStreamNormalizer:
        """Create a Gemini normalizer instance."""
        return GeminiStreamNormalizer()

    @pytest.mark.asyncio
    async def test_normalizes_simple_text_chunk(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test normalization of simple text chunk."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Hello"}], "role": "model"},
                        "index": 0,
                    }
                ],
                "modelVersion": "gemini-pro",
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # Should have content chunk + done marker
        assert len(chunks) == 2

        chunk = chunks[0]
        assert isinstance(chunk, StreamingContent)
        assert chunk.content == "Hello"
        assert chunk.metadata["provider"] == "gemini"
        assert chunk.metadata["model"] == "gemini-pro"
        assert chunk.metadata["role"] == "model"
        assert chunk.metadata["index"] == 0
        assert chunk.is_done is False
        assert chunk.is_empty is False

        # Done marker
        assert chunks[1].is_done is True
        assert SentinelManager.is_done_marker(chunks[1])

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_finish_reason(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test normalization of chunk with finishReason."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Done"}], "role": "model"},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert chunk.content == "Done"
        assert chunk.metadata["finish_reason"] == "stop"
        assert chunk.is_done is True
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_maps_finish_reasons_correctly(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test mapping of various finishReason values."""
        test_cases = [
            ("STOP", "stop"),
            ("MAX_TOKENS", "length"),
            ("SAFETY", "content_filter"),
            ("RECITATION", "content_filter"),
            ("OTHER", "stop"),
        ]

        for gemini_reason, expected_reason in test_cases:
            # Arrange
            def create_mock_stream(reason: str):
                async def mock_stream():
                    yield json.dumps(
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [{"text": "Test"}],
                                        "role": "model",
                                    },
                                    "finishReason": reason,
                                }
                            ]
                        }
                    )

                return mock_stream()

            # Act
            chunks = [
                chunk
                async for chunk in normalizer.normalize_stream(
                    create_mock_stream(gemini_reason), "gemini"
                )
            ]

            # Assert
            assert chunks[0].metadata["finish_reason"] == expected_reason

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_function_call(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test normalization of chunk with function_call."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "get_weather",
                                        "args": {"location": "NYC", "unit": "celsius"},
                                    }
                                }
                            ],
                            "role": "model",
                        },
                        "index": 0,
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert "tool_calls" in chunk.metadata
        assert len(chunk.metadata["tool_calls"]) == 1

        tool_call = chunk.metadata["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "get_weather"

        # Parse arguments to verify structure
        args = json.loads(tool_call["function"]["arguments"])
        assert args["location"] == "NYC"
        assert args["unit"] == "celsius"
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_normalizes_chunk_with_text_and_function_call(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test normalization of chunk with both text and function_call."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Let me check the weather for you."},
                                {
                                    "functionCall": {
                                        "name": "get_weather",
                                        "args": {"location": "NYC"},
                                    }
                                },
                            ],
                            "role": "model",
                        },
                        "index": 0,
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert chunk.content == "Let me check the weather for you."
        assert "tool_calls" in chunk.metadata
        assert len(chunk.metadata["tool_calls"]) == 1
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_normalizes_multiple_text_parts(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test normalization of chunk with multiple text parts."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Hello "},
                                {"text": "world"},
                                {"text": "!"},
                            ],
                            "role": "model",
                        }
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        # Text parts should be concatenated
        assert chunk.content == "Hello world!"
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_empty_candidates(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of chunks with empty candidates array."""
        # Arrange
        raw_chunk = json.dumps({"candidates": []})

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # Empty candidates should be skipped, only done marker emitted
        assert len(chunks) == 1
        assert chunks[0].is_done is True

    @pytest.mark.asyncio
    async def test_handles_empty_parts(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of chunks with empty parts array."""
        # Arrange
        raw_chunk = json.dumps(
            {"candidates": [{"content": {"parts": [], "role": "model"}, "index": 0}]}
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert chunk.content == ""
        assert chunk.is_empty is True
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_multiple_json_lines(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of multiple JSON objects in JSON-lines format."""
        # Arrange
        chunk1 = json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "Hello"}], "role": "model"}}
                ],
                "id": "gen_123",
            }
        )
        chunk2 = json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": " world"}], "role": "model"}}
                ],
                "id": "gen_123",
            }
        )

        raw_chunk = f"{chunk1}\n{chunk2}"

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # 2 content chunks + 1 done marker
        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " world"
        assert chunks[2].is_done is True

    @pytest.mark.asyncio
    async def test_preserves_stream_id_across_chunks(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test that stream_id is preserved across all chunks."""

        # Arrange
        async def mock_stream():
            yield json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Hello"}], "role": "model"}}
                    ],
                    "id": "gen_123",
                }
            )
            yield json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": " world"}], "role": "model"}}
                    ],
                    "id": "gen_123",
                }
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # 2 content chunks + 1 done marker
        assert len(chunks) == 3

        # All chunks should have the same stream_id
        stream_id = chunks[0].stream_id
        assert stream_id == "gen_123"

        for chunk in chunks:
            assert chunk.stream_id == stream_id
            if not chunk.is_done or chunk.metadata.get("stream_id"):
                assert (
                    chunk.metadata.get("stream_id") == stream_id
                    or chunk.metadata.get("id") == stream_id
                )

    @pytest.mark.asyncio
    async def test_handles_bytes_input(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of bytes input."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {"content": {"parts": [{"text": "Hello"}], "role": "model"}}
                ]
            }
        ).encode("utf-8")

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2
        assert chunks[0].content == "Hello"
        assert chunks[0].metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_malformed_json(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of malformed JSON."""
        # Arrange
        raw_chunk = '{"invalid json'

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # Malformed JSON should be skipped, only done marker emitted
        assert len(chunks) == 1
        assert chunks[0].is_done is True

    @pytest.mark.asyncio
    async def test_handles_stream_error(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of errors during streaming."""

        # Arrange
        async def mock_stream():
            yield json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Hello"}], "role": "model"}}
                    ]
                }
            )
            raise Exception("Stream error")

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        # First chunk is content
        assert chunks[0].content == "Hello"
        assert chunks[0].is_done is False

        # Second chunk is error
        assert chunks[1].is_done is True
        assert "error" in chunks[1].metadata
        assert chunks[1].metadata["finish_reason"] == "error"
        assert chunks[1].metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_function_call_without_id(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of function_call without explicit id."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "get_weather",
                                        "args": {"location": "NYC"},
                                    }
                                }
                            ],
                            "role": "model",
                        }
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert "tool_calls" in chunk.metadata
        tool_call = chunk.metadata["tool_calls"][0]

        # Should generate an id based on function name
        assert tool_call["id"].startswith("call_")
        assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_function_call_without_name(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of function_call without name (invalid)."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"functionCall": {"args": {"location": "NYC"}}}],
                            "role": "model",
                        }
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        # Invalid function call should be skipped
        assert (
            "tool_calls" not in chunk.metadata or len(chunk.metadata["tool_calls"]) == 0
        )

    @pytest.mark.asyncio
    async def test_metadata_mapping_completeness(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test that all Gemini metadata fields are mapped correctly."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Test"}], "role": "model"},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "modelVersion": "gemini-pro",
                "id": "gen_123",
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        # Verify all metadata fields are present
        assert chunk.metadata["provider"] == "gemini"
        assert chunk.metadata["model"] == "gemini-pro"
        assert chunk.metadata["id"] == "gen_123"
        assert chunk.metadata["role"] == "model"
        assert chunk.metadata["finish_reason"] == "stop"
        assert chunk.metadata["index"] == 0
        assert chunk.metadata["stream_id"] == "gen_123"

        # Verify chunk passes validation
        assert normalizer.validate_chunk(chunk)

    @pytest.mark.asyncio
    async def test_complete_streaming_session(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test a complete streaming session with multiple chunks."""

        # Arrange
        async def mock_stream():
            # Initial chunk
            yield json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "Hello"}], "role": "model"}}
                    ],
                    "modelVersion": "gemini-pro",
                    "id": "gen_123",
                }
            )
            # Content chunk
            yield json.dumps(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": " world"}], "role": "model"}}
                    ],
                    "id": "gen_123",
                }
            )
            # Final chunk with finish reason
            yield json.dumps(
                {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "!"}], "role": "model"},
                            "finishReason": "STOP",
                        }
                    ],
                    "id": "gen_123",
                }
            )

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        # 3 content chunks + 1 done marker
        assert len(chunks) == 4

        # Content chunks
        assert chunks[0].content == "Hello"
        assert chunks[0].is_done is False
        assert chunks[1].content == " world"
        assert chunks[1].is_done is False
        assert chunks[2].content == "!"
        assert chunks[2].is_done is True
        assert chunks[2].metadata["finish_reason"] == "stop"

        # Done sentinel
        assert chunks[3].is_done is True
        assert SentinelManager.is_done_marker(chunks[3])

        # All chunks have same stream_id
        stream_id = chunks[0].stream_id
        for chunk in chunks:
            assert chunk.stream_id == stream_id
            assert chunk.metadata["provider"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_multiple_function_calls(
        self, normalizer: GeminiStreamNormalizer
    ) -> None:
        """Test handling of multiple function calls in one chunk."""
        # Arrange
        raw_chunk = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "get_weather",
                                        "args": {"location": "NYC"},
                                    }
                                },
                                {
                                    "functionCall": {
                                        "name": "get_time",
                                        "args": {"timezone": "EST"},
                                    }
                                },
                            ],
                            "role": "model",
                        }
                    }
                ]
            }
        )

        async def mock_stream():
            yield raw_chunk

        # Act
        chunks = [
            chunk
            async for chunk in normalizer.normalize_stream(mock_stream(), "gemini")
        ]

        # Assert
        assert len(chunks) == 2

        chunk = chunks[0]
        assert "tool_calls" in chunk.metadata
        assert len(chunk.metadata["tool_calls"]) == 2

        # Verify both function calls are mapped
        assert chunk.metadata["tool_calls"][0]["function"]["name"] == "get_weather"
        assert chunk.metadata["tool_calls"][1]["function"]["name"] == "get_time"
        assert chunk.metadata["provider"] == "gemini"
