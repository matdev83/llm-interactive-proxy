"""Anthropic API streaming emulator."""

from __future__ import annotations

import json

from tests.streaming_regression.emulators.base_emulator import StreamingEmulatorBase


class AnthropicStreamingEmulator(StreamingEmulatorBase):
    """Emulates Anthropic streaming API responses."""

    backend_type = "anthropic"

    @staticmethod
    def create_text_chunks(text: str, chunk_size: int = 10) -> list[str]:
        """Create realistic Anthropic SSE chunks from text.

        Args:
            text: Text to split into chunks
            chunk_size: Approximate characters per chunk

        Returns:
            List of SSE-formatted chunks
        """
        chunks = []

        # Message start event
        start_event = {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-3-5-sonnet-20241022",
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
        chunks.append(f"event: message_start\ndata: {json.dumps(start_event)}\n\n")

        # Content block start
        content_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        chunks.append(
            f"event: content_block_start\ndata: {json.dumps(content_start)}\n\n"
        )

        # Content deltas
        words = text.split()
        current_chunk = []
        current_length = 0

        for word in words:
            current_chunk.append(word)
            current_length += len(word) + 1

            if current_length >= chunk_size:
                chunk_text = " ".join(current_chunk)
                delta_event = {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": chunk_text},
                }
                chunks.append(
                    f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
                )
                current_chunk = []
                current_length = 0

        # Add remaining words
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            delta_event = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": chunk_text},
            }
            chunks.append(
                f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
            )

        # Content block stop
        block_stop = {"type": "content_block_stop", "index": 0}
        chunks.append(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n")

        # Message delta (usage update)
        message_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 50},
        }
        chunks.append(f"event: message_delta\ndata: {json.dumps(message_delta)}\n\n")

        # Message stop
        message_stop = {"type": "message_stop"}
        chunks.append(f"event: message_stop\ndata: {json.dumps(message_stop)}\n\n")

        return chunks

    @staticmethod
    def create_tool_call_chunks() -> list[str]:
        """Create Anthropic SSE chunks with tool calls.

        Returns:
            List of SSE-formatted chunks with tool call
        """
        chunks = []

        # Message start
        start_event = {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-3-5-sonnet-20241022",
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
        chunks.append(f"event: message_start\ndata: {json.dumps(start_event)}\n\n")

        # Tool use block start
        tool_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_test",
                "name": "read_file",
                "input": {},
            },
        }
        chunks.append(f"event: content_block_start\ndata: {json.dumps(tool_start)}\n\n")

        # Tool input deltas (streamed JSON)
        input_parts = ['{"path":', ' "test.py"}']
        for part in input_parts:
            delta_event = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": part},
            }
            chunks.append(
                f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
            )

        # Content block stop
        block_stop = {"type": "content_block_stop", "index": 0}
        chunks.append(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n")

        # Message delta
        message_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 30},
        }
        chunks.append(f"event: message_delta\ndata: {json.dumps(message_delta)}\n\n")

        # Message stop
        message_stop = {"type": "message_stop"}
        chunks.append(f"event: message_stop\ndata: {json.dumps(message_stop)}\n\n")

        return chunks

    @staticmethod
    def create_thinking_chunks(thinking: str, response: str) -> list[str]:
        """Create Anthropic SSE chunks with thinking content.

        Args:
            thinking: Thinking text
            response: Response text

        Returns:
            List of SSE-formatted chunks with thinking
        """
        chunks = []

        # Message start
        start_event = {
            "type": "message_start",
            "message": {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-3-5-sonnet-20241022",
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
        chunks.append(f"event: message_start\ndata: {json.dumps(start_event)}\n\n")

        # Thinking block start
        thinking_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "thinking", "thinking": ""},
        }
        chunks.append(
            f"event: content_block_start\ndata: {json.dumps(thinking_start)}\n\n"
        )

        # Thinking deltas
        thinking_words = thinking.split()
        for i in range(0, len(thinking_words), 5):
            chunk_text = " ".join(thinking_words[i : i + 5])
            delta_event = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": chunk_text},
            }
            chunks.append(
                f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
            )

        # Thinking block stop
        block_stop = {"type": "content_block_stop", "index": 0}
        chunks.append(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n")

        # Text block start
        text_start = {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "text", "text": ""},
        }
        chunks.append(f"event: content_block_start\ndata: {json.dumps(text_start)}\n\n")

        # Text deltas
        response_words = response.split()
        for i in range(0, len(response_words), 5):
            chunk_text = " ".join(response_words[i : i + 5])
            delta_event = {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": chunk_text},
            }
            chunks.append(
                f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
            )

        # Text block stop
        block_stop = {"type": "content_block_stop", "index": 1}
        chunks.append(f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n")

        # Message delta
        message_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 100},
        }
        chunks.append(f"event: message_delta\ndata: {json.dumps(message_delta)}\n\n")

        # Message stop
        message_stop = {"type": "message_stop"}
        chunks.append(f"event: message_stop\ndata: {json.dumps(message_stop)}\n\n")

        return chunks
