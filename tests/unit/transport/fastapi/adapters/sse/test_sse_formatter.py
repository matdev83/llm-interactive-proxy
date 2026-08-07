"""Tests for SSEFormatter."""

from __future__ import annotations

import json

from src.core.transport.fastapi.adapters.protocols import ISSEFormatter
from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter


class TestSSEFormatter:
    """Test SSEFormatter implementation."""

    def test_formatter_implements_protocol(self) -> None:
        """Test that SSEFormatter implements ISSEFormatter protocol."""
        formatter: ISSEFormatter = SSEFormatter()
        assert isinstance(formatter, SSEFormatter)

    def test_format_dict_produces_sse_format(self) -> None:
        """Test dict formatting produces correct SSE format."""
        formatter = SSEFormatter()
        chunk = {"test": "data", "value": 123}
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")

        # Extract JSON part
        json_part = decoded[6:-2]  # Remove "data: " and "\n\n"
        parsed = json.loads(json_part)
        assert parsed == chunk

    def test_format_openai_dict_coerces_numeric_id(self) -> None:
        formatter = SSEFormatter()
        chunk = {
            "id": 777,
            "object": "chat.completion.chunk",
            "created": 9,
            "model": "m",
            "choices": [{"index": 0, "delta": {"content": "a"}}],
        }
        decoded = formatter.format_chunk(chunk).decode("utf-8")
        parsed = json.loads(decoded[6:-2])
        assert parsed["id"] == "777"
        assert chunk["id"] == 777

    def test_format_bytes_passthrough(self) -> None:
        """Test bytes pass-through."""
        formatter = SSEFormatter()
        chunk = b"test bytes content"
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        assert result == chunk

    def test_format_string_encoding(self) -> None:
        """Test string encoding to bytes."""
        formatter = SSEFormatter()
        chunk = "test string content"
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        assert result == chunk.encode("utf-8")

    def test_format_empty_dict(self) -> None:
        """Test empty dict handling."""
        formatter = SSEFormatter()
        chunk = {}
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        assert decoded == "data: {}\n\n"

    def test_format_empty_string(self) -> None:
        """Test empty string handling."""
        formatter = SSEFormatter()
        chunk = ""
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        assert result == b""

    def test_format_empty_bytes(self) -> None:
        """Test empty bytes handling."""
        formatter = SSEFormatter()
        chunk = b""
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        assert result == b""

    def test_format_special_characters_in_json(self) -> None:
        """Test special characters in JSON."""
        formatter = SSEFormatter()
        chunk = {
            "text": "Line 1\nLine 2",
            "quote": 'He said "Hello"',
            "unicode": "测试 Unicode",
            "backslash": "path\\to\\file",
        }
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        assert decoded.startswith("data: ")
        assert decoded.endswith("\n\n")

        json_part = decoded[6:-2]
        parsed = json.loads(json_part)
        assert parsed == chunk

    def test_format_nested_dict(self) -> None:
        """Test nested dict formatting."""
        formatter = SSEFormatter()
        chunk = {
            "outer": {
                "inner": {"deep": "value"},
                "list": [1, 2, 3],
            },
            "simple": "text",
        }
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        decoded = result.decode("utf-8")
        json_part = decoded[6:-2]
        parsed = json.loads(json_part)
        assert parsed == chunk

    def test_format_unicode_string(self) -> None:
        """Test unicode string encoding."""
        formatter = SSEFormatter()
        chunk = "测试内容 Unicode"
        result = formatter.format_chunk(chunk)

        assert isinstance(result, bytes)
        assert result.decode("utf-8") == chunk

    def test_format_property_valid_sse(self) -> None:
        """Property test: format is always valid SSE."""
        formatter = SSEFormatter()

        test_cases = [
            {"simple": "dict"},
            {"nested": {"deep": "value"}},
            {"list": [1, 2, 3]},
            {"unicode": "测试 Unicode"},
            b"raw bytes",
            "plain string",
            "",
            b"",
        ]

        for chunk in test_cases:
            result = formatter.format_chunk(chunk)
            assert isinstance(result, bytes)

            if isinstance(chunk, dict):
                decoded = result.decode("utf-8")
                assert decoded.startswith("data: ")
                assert decoded.endswith("\n\n")
                # Verify JSON is valid
                json_part = decoded[6:-2]
                json.loads(json_part)  # Should not raise
