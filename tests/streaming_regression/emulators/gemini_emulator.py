"""Gemini API streaming emulator."""

from __future__ import annotations

import json

from tests.streaming_regression.emulators.base_emulator import StreamingEmulatorBase


class GeminiStreamingEmulator(StreamingEmulatorBase):
    """Emulates Gemini streaming API responses."""

    backend_type = "gemini"

    @staticmethod
    def create_text_chunks(text: str, chunk_size: int = 10) -> list[str]:
        """Create realistic Gemini streaming chunks from text.

        Args:
            text: Text to split into chunks
            chunk_size: Approximate characters per chunk

        Returns:
            List of JSON-formatted chunks
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
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": chunk_text}],
                                "role": "model",
                            },
                            "finishReason": "STOP" if current_length > 100 else None,
                        }
                    ]
                }
                chunks.append(json.dumps(chunk_data) + "\n")
                current_chunk = []
                current_length = 0

        # Add remaining words
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunk_data = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": chunk_text}],
                            "role": "model",
                        },
                        "finishReason": None,
                    }
                ]
            }
            chunks.append(json.dumps(chunk_data) + "\n")

        # Final chunk with finish reason
        final_chunk = {
            "candidates": [
                {
                    "content": {"parts": [], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 50,
                "totalTokenCount": 60,
            },
        }
        chunks.append(json.dumps(final_chunk) + "\n")

        return chunks

    @staticmethod
    def create_function_call_chunks() -> list[str]:
        """Create Gemini streaming chunks with function calls.

        Returns:
            List of JSON-formatted chunks with function call
        """
        chunks = []

        # Function call chunk
        function_chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "read_file",
                                    "args": {"path": "test.py"},
                                }
                            }
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 20,
                "totalTokenCount": 30,
            },
        }
        chunks.append(json.dumps(function_chunk) + "\n")

        return chunks

    @staticmethod
    def create_thinking_chunks(thinking: str, response: str) -> list[str]:
        """Create Gemini streaming chunks with thinking content.

        Note: Gemini doesn't have native thinking support, but we can
        simulate it with text that includes thinking tags.

        Args:
            thinking: Thinking text
            response: Response text

        Returns:
            List of JSON-formatted chunks
        """
        chunks = []

        # Thinking chunks (wrapped in tags)
        thinking_text = f"<thinking>{thinking}</thinking>"
        thinking_words = thinking_text.split()
        for i in range(0, len(thinking_words), 5):
            chunk_text = " ".join(thinking_words[i : i + 5])
            chunk_data = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": chunk_text}],
                            "role": "model",
                        },
                        "finishReason": None,
                    }
                ]
            }
            chunks.append(json.dumps(chunk_data) + "\n")

        # Response chunks
        response_words = response.split()
        for i in range(0, len(response_words), 5):
            chunk_text = " ".join(response_words[i : i + 5])
            chunk_data = {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": chunk_text}],
                            "role": "model",
                        },
                        "finishReason": None,
                    }
                ]
            }
            chunks.append(json.dumps(chunk_data) + "\n")

        # Final chunk
        final_chunk = {
            "candidates": [
                {
                    "content": {"parts": [], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 10,
                "candidatesTokenCount": 100,
                "totalTokenCount": 110,
            },
        }
        chunks.append(json.dumps(final_chunk) + "\n")

        return chunks
