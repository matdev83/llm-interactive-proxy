"""OpenAI API streaming emulator."""

from __future__ import annotations

from typing import Any

from tests.streaming_regression.emulators.base_emulator import StreamingEmulatorBase


class OpenAIStreamingEmulator(StreamingEmulatorBase):
    """Emulates OpenAI streaming API responses."""

    backend_type = "openai"

    @staticmethod
    def create_text_chunks(text: str, chunk_size: int = 10) -> list[dict[str, Any]]:
        """Create realistic OpenAI chunks from text.

        Args:
            text: Text to split into chunks
            chunk_size: Approximate characters per chunk

        Returns:
            List of chunk dictionaries (not SSE-formatted)
        """
        chunks = []
        words = text.split()
        current_chunk = []
        current_length = 0

        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1

            if current_length >= chunk_size:
                chunk_text = " ".join(current_chunk)
                chunk_data = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion.chunk",
                    "created": 1234567890,
                    "model": "gpt-4",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk_text},
                            "finish_reason": None,
                        }
                    ],
                }
                chunks.append(chunk_data)
                current_chunk = []
                current_length = 0

        # Add remaining words
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunk_data = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk_text},
                        "finish_reason": None,
                    }
                ],
            }
            chunks.append(chunk_data)

        # Add final chunk
        final_chunk = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        chunks.append(final_chunk)

        return chunks

    @staticmethod
    def create_tool_call_chunks() -> list[dict[str, Any]]:
        """Create OpenAI chunks with tool calls.

        Returns:
            List of chunk dictionaries with tool call
        """
        chunks = []

        # Tool call start
        chunk1 = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        }
        chunks.append(chunk1)

        # Tool call arguments (streamed)
        args_parts = ['{"path":', ' "test.py"}']
        for arg_part in args_parts:
            chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": arg_part}}
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            }
            chunks.append(chunk)

        # Final chunk
        final_chunk = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        }
        chunks.append(final_chunk)

        return chunks

    @staticmethod
    def create_reasoning_chunks(reasoning: str, response: str) -> list[dict[str, Any]]:
        """Create OpenAI chunks with reasoning content.

        Args:
            reasoning: Reasoning text
            response: Response text

        Returns:
            List of chunk dictionaries with reasoning
        """
        chunks = []

        # Reasoning chunks
        reasoning_words = reasoning.split()
        for i in range(0, len(reasoning_words), 5):
            chunk_text = " ".join(reasoning_words[i : i + 5])
            chunk_data = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"reasoning_content": chunk_text},
                        "finish_reason": None,
                    }
                ],
            }
            chunks.append(chunk_data)

        # Response chunks
        response_words = response.split()
        for i in range(0, len(response_words), 5):
            chunk_text = " ".join(response_words[i : i + 5])
            chunk_data = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk_text},
                        "finish_reason": None,
                    }
                ],
            }
            chunks.append(chunk_data)

        # Final chunk
        final_chunk = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        chunks.append(final_chunk)

        return chunks
