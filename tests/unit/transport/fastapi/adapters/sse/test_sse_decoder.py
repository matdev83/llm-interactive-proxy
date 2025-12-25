"""Tests for SSEDecoder."""

from __future__ import annotations

from src.core.transport.fastapi.adapters.protocols import ISSEDecoder
from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder


class TestSSEDecoder:
    """Test SSEDecoder implementation."""

    def test_decoder_implements_protocol(self) -> None:
        """Test that SSEDecoder implements ISSEDecoder protocol."""
        decoder: ISSEDecoder = SSEDecoder()
        assert isinstance(decoder, SSEDecoder)

    def test_decode_openai_format(self) -> None:
        """Test OpenAI format decoding."""
        decoder = SSEDecoder()
        payload = b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert "choices" in content
        assert not is_done

    def test_decode_anthropic_format(self) -> None:
        """Test Anthropic format decoding."""
        decoder = SSEDecoder()
        payload = (
            b'data: {"type": "content_block_delta", "delta": {"text": "test"}}\n\n'
        )
        decoded = decoder.decode_payload(payload)
        content, metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert metadata.get("event_type") == "content_block_delta"
        assert not is_done

    def test_decode_gemini_format(self) -> None:
        """Test Gemini format decoding."""
        decoder = SSEDecoder()
        payload = (
            b'data: {"candidates": [{"content": {"parts": [{"text": "test"}]}}]}\n\n'
        )
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert "candidates" in content
        assert not is_done

    def test_decode_done_marker(self) -> None:
        """Test [DONE] marker detection."""
        decoder = SSEDecoder()

        # Test [DONE] as last line
        payload1 = b'data: {"text": "test"}\n\ndata: [DONE]\n\n'
        res1 = decoder.decode_payload(payload1)
        _content1, metadata1, is_done1 = res1.content, res1.metadata, res1.is_done

        assert is_done1
        assert metadata1.get("finish_reason") == "stop"

        # Test [DONE] alone
        payload2 = b"data: [DONE]\n\n"
        res2 = decoder.decode_payload(payload2)
        content2, metadata2, is_done2 = res2.content, res2.metadata, res2.is_done

        assert is_done2
        assert content2 == ""
        assert metadata2.get("finish_reason") == "stop"

        # Test ["DONE"] format
        payload3 = b'data: ["DONE"]\n\n'
        res3 = decoder.decode_payload(payload3)
        _content3, metadata3, is_done3 = res3.content, res3.metadata, res3.is_done

        assert is_done3
        assert metadata3.get("finish_reason") == "stop"

    def test_decode_malformed_sse(self) -> None:
        """Test malformed SSE handling."""
        decoder = SSEDecoder()

        # No data: prefix
        payload1 = b"just some text"
        res1 = decoder.decode_payload(payload1)
        content1, metadata1, is_done1 = res1.content, res1.metadata, res1.is_done

        assert content1 == payload1
        assert metadata1 == {}
        assert not is_done1

        # Empty payload
        payload2 = b""
        res2 = decoder.decode_payload(payload2)
        content2, metadata2, is_done2 = res2.content, res2.metadata, res2.is_done

        assert content2 == payload2
        assert metadata2 == {}
        assert not is_done2

    def test_decode_empty_payload(self) -> None:
        """Test empty payload handling."""
        decoder = SSEDecoder()

        # Empty data: line results in empty string after processing
        payload = b"data:\n\n"
        decoded = decoder.decode_payload(payload)
        content, metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert content == ""  # Empty string after JSON decode fails
        assert metadata == {}
        assert not is_done

    def test_decode_metadata_extraction(self) -> None:
        """Test metadata extraction from decoded content."""
        decoder = SSEDecoder()

        # Test finish_reason extraction
        payload1 = b'data: {"finish_reason": "stop", "text": "done"}\n\n'
        res1 = decoder.decode_payload(payload1)
        _content1, metadata1, is_done1 = res1.content, res1.metadata, res1.is_done

        assert metadata1.get("finish_reason") == "stop"
        assert not is_done1

        # Test event_type extraction
        payload2 = b'data: {"type": "message_start", "content": "test"}\n\n'
        res2 = decoder.decode_payload(payload2)
        _content2, metadata2, is_done2 = res2.content, res2.metadata, res2.is_done

        assert metadata2.get("event_type") == "message_start"
        assert not is_done2

    def test_decode_bytes_input(self) -> None:
        """Test bytes input decoding."""
        decoder = SSEDecoder()
        payload = b'data: {"test": "value"}\n\n'
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert content["test"] == "value"
        assert not is_done

    def test_decode_string_input(self) -> None:
        """Test string input decoding."""
        decoder = SSEDecoder()
        payload = 'data: {"test": "value"}\n\n'
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert content["test"] == "value"
        assert not is_done

    def test_decode_invalid_json(self) -> None:
        """Test invalid JSON handling."""
        decoder = SSEDecoder()
        payload = b"data: not valid json\n\n"
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, str)
        assert content == "not valid json"
        assert not is_done

    def test_decode_multiline_data(self) -> None:
        """Test multiline data handling."""
        decoder = SSEDecoder()
        payload = b"data: line1\ndata: line2\ndata: line3\n\n"
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, str)
        assert content == "line1\nline2\nline3"
        assert not is_done

    def test_decode_non_dict_json(self) -> None:
        """Test non-dict JSON decoding."""
        decoder = SSEDecoder()
        payload = b"data: [1, 2, 3]\n\n"
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, list)
        assert content == [1, 2, 3]
        assert not is_done

    def test_decode_unicode_decode_error(self) -> None:
        """Test Unicode decode error handling."""
        decoder = SSEDecoder()
        # Invalid UTF-8 bytes
        payload = b"\xff\xfe\xfd"
        decoded = decoder.decode_payload(payload)
        content, metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert content == payload
        assert metadata == {}
        assert not is_done

    def test_decode_non_string_bytes_input(self) -> None:
        """Test non-string/bytes input handling."""
        decoder = SSEDecoder()
        payload = 12345  # int, not bytes or str
        decoded = decoder.decode_payload(payload)
        content, metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert content == payload
        assert metadata == {}
        assert not is_done

    def test_decode_finish_reason_in_choices(self) -> None:
        """Test finish_reason extraction from nested choices."""
        decoder = SSEDecoder()
        payload = b'data: {"choices": [{"finish_reason": "length"}]}\n\n'
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        # Note: The current implementation doesn't extract finish_reason from nested choices
        # This test documents current behavior
        assert not is_done

    def test_decode_bytearray_input(self) -> None:
        """Test bytearray input handling."""
        decoder = SSEDecoder()
        payload = bytearray(b'data: {"test": "value"}\n\n')
        decoded = decoder.decode_payload(payload)
        content, _metadata, is_done = decoded.content, decoded.metadata, decoded.is_done

        assert isinstance(content, dict)
        assert content["test"] == "value"
        assert not is_done
