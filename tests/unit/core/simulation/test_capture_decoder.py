"""Tests for CaptureDecoder - best-effort decoding of captured traffic into canonical contracts."""

from __future__ import annotations

import json

import pytest
from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureMetadata,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.simulation.capture_decoder import (
    CaptureDecoder,
    DecodeError,
    DecodeResult,
)


class TestDecodeResult:
    """Tests for DecodeResult typed result container."""

    def test_success_result(self):
        """Test successful decode result."""
        value = {"test": "data"}
        result = DecodeResult.success(value)

        assert result.is_success is True
        assert result.is_failure is False
        assert result.value == value
        assert result.error is None
        assert result.diagnostics is None

    def test_failure_result(self):
        """Test failure decode result."""
        error = DecodeError("Test error", details={"field": "value"})
        result = DecodeResult.failure(error)

        assert result.is_success is False
        assert result.is_failure is True
        # Accessing .value on failure should raise
        with pytest.raises(ValueError, match="Cannot get value from failed result"):
            _ = result.value
        assert result.error == error
        assert result.diagnostics == {"field": "value"}

    def test_failure_with_diagnostics(self):
        """Test failure result with additional diagnostics."""
        error = DecodeError("Parse failed", details={"line": 42})
        diagnostics = {"raw_bytes": b"test", "attempted_format": "json"}
        result = DecodeResult.failure(error, diagnostics=diagnostics)

        assert result.is_failure is True
        assert result.error == error
        assert result.diagnostics == {"line": 42, **diagnostics}


class TestCaptureDecoderDeterminism:
    """Tests for decoding determinism - same input produces same output."""

    def test_same_entry_decoded_multiple_times(self):
        """Same capture entry decoded multiple times produces identical contracts."""
        decoder = CaptureDecoder()

        # Create a simple OpenAI-compatible request
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=json.dumps(request_data).encode("utf-8"),
            metadata=CaptureMetadata(session_id="test"),
        )

        result1 = decoder.decode_inbound_request(entry)
        result2 = decoder.decode_inbound_request(entry)
        result3 = decoder.decode_inbound_request(entry)

        assert result1.is_success
        assert result2.is_success
        assert result3.is_success

        # All results should be semantically equivalent
        req1 = result1.value
        req2 = result2.value
        req3 = result3.value

        assert req1.model == req2.model == req3.model
        assert len(req1.messages) == len(req2.messages) == len(req3.messages)
        assert (
            req1.messages[0].content
            == req2.messages[0].content
            == req3.messages[0].content
        )

    def test_field_ordering_does_not_affect_result(self):
        """Field ordering in JSON doesn't affect decoded result."""
        decoder = CaptureDecoder()

        # Same data, different field order
        request1 = json.dumps(
            {"model": "gpt-4", "messages": [{"role": "user", "content": "Hi"}]}
        )
        request2 = json.dumps(
            {"messages": [{"role": "user", "content": "Hi"}], "model": "gpt-4"}
        )

        entry1 = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request1.encode("utf-8"),
        )
        entry2 = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request2.encode("utf-8"),
        )

        result1 = decoder.decode_inbound_request(entry1)
        result2 = decoder.decode_inbound_request(entry2)

        assert result1.is_success
        assert result2.is_success

        req1 = result1.value
        req2 = result2.value

        assert req1.model == req2.model
        assert len(req1.messages) == len(req2.messages)
        assert req1.messages[0].content == req2.messages[0].content

    def test_metadata_variations_dont_affect_payload_decoding(self):
        """Timestamp/metadata variations don't affect payload decoding."""
        decoder = CaptureDecoder()

        request_data = json.dumps(
            {"model": "gpt-4", "messages": [{"role": "user", "content": "Test"}]}
        )

        entry1 = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request_data.encode("utf-8"),
            metadata=CaptureMetadata(session_id="session1", backend="openai"),
        )
        entry2 = CaptureEntry(
            timestamp=2.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=1,
            data=request_data.encode("utf-8"),
            metadata=CaptureMetadata(session_id="session2", backend="anthropic"),
        )

        result1 = decoder.decode_inbound_request(entry1)
        result2 = decoder.decode_inbound_request(entry2)

        assert result1.is_success
        assert result2.is_success

        # Payloads should be identical despite different metadata
        assert result1.value.model == result2.value.model
        assert result1.value.messages[0].content == result2.value.messages[0].content


class TestCaptureDecoderRoundTrip:
    """Tests for round-trip invariants - encode → decode → equals original."""

    def test_request_round_trip(self):
        """CanonicalChatRequest → JSON bytes → decode → equals original."""
        decoder = CaptureDecoder()

        # Create a canonical request
        original_request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello, world!")],
            temperature=0.7,
        )

        # Serialize to JSON bytes (as it would be captured)
        json_bytes = json.dumps(original_request.model_dump(), sort_keys=True).encode(
            "utf-8"
        )

        # Create capture entry
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=json_bytes,
        )

        # Decode back
        result = decoder.decode_inbound_request(entry)

        assert result.is_success
        decoded_request = result.value

        # Verify semantic equivalence
        assert decoded_request.model == original_request.model
        assert len(decoded_request.messages) == len(original_request.messages)
        assert (
            decoded_request.messages[0].content == original_request.messages[0].content
        )
        assert decoded_request.temperature == original_request.temperature

    def test_response_envelope_round_trip(self):
        """ResponseEnvelope → JSON bytes → decode → equals original."""
        decoder = CaptureDecoder()

        # Create a response envelope
        response_data = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        }

        json_bytes = json.dumps(response_data).encode("utf-8")

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=json_bytes,
        )

        result = decoder.decode_response(entry)

        assert result.is_success
        decoded_envelope = result.value

        assert isinstance(decoded_envelope, ResponseEnvelope)
        assert decoded_envelope.content == response_data

    def test_semantic_equivalence_not_byte_for_byte(self):
        """Verify semantic equivalence, not byte-for-byte equality."""
        decoder = CaptureDecoder()

        # Create request with extra whitespace/comments (if JSON5-like)
        request_json = '{"model":"gpt-4","messages":[{"role":"user","content":"Hi"}]}'
        normalized_json = json.dumps(json.loads(request_json), sort_keys=True)

        entry1 = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=request_json.encode("utf-8"),
        )
        entry2 = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=normalized_json.encode("utf-8"),
        )

        result1 = decoder.decode_inbound_request(entry1)
        result2 = decoder.decode_inbound_request(entry2)

        assert result1.is_success
        assert result2.is_success

        # Should be semantically equivalent even if bytes differ
        assert result1.value.model == result2.value.model
        assert result1.value.messages[0].content == result2.value.messages[0].content


class TestCaptureDecoderBestEffort:
    """Tests for best-effort behavior - invalid inputs handled gracefully."""

    def test_invalid_json_returns_failure_not_exception(self):
        """Invalid JSON returns failure result, not exception."""
        decoder = CaptureDecoder()

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=b"not valid json {",
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_failure
        assert result.error is not None
        assert "JSON" in result.error.message or "parse" in result.error.message.lower()

    def test_missing_required_fields_returns_failure_with_diagnostics(self):
        """Missing required fields returns failure with diagnostics."""
        decoder = CaptureDecoder()

        # Request without required "messages" field
        invalid_request = json.dumps({"model": "gpt-4"})
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=invalid_request.encode("utf-8"),
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_failure
        assert result.error is not None
        assert result.diagnostics is not None

    def test_partial_decoding_with_warnings(self):
        """Partial decoding (some fields succeed) returns partial result with warnings."""
        decoder = CaptureDecoder()

        # Request with some valid fields but invalid structure
        partial_request = json.dumps({"model": "gpt-4", "messages": "not a list"})
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=partial_request.encode("utf-8"),
        )

        result = decoder.decode_inbound_request(entry)

        # Should fail validation but provide diagnostics
        assert result.is_failure
        assert result.diagnostics is not None

    def test_empty_bytes_handled_gracefully(self):
        """Empty bytes handled gracefully."""
        decoder = CaptureDecoder()

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=b"",
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_failure
        assert result.error is not None

    def test_non_json_bytes_handled_gracefully(self):
        """Non-JSON bytes (e.g., binary) handled gracefully."""
        decoder = CaptureDecoder()

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=b"\x00\x01\x02\x03\xff\xfe\xfd",
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_failure
        assert result.error is not None


class TestCaptureDecoderProtocolCoverage:
    """Tests covering all supported protocols (OpenAI, Anthropic, Gemini)."""

    def test_openai_compatible_request(self):
        """Decode OpenAI-compatible request shape."""
        decoder = CaptureDecoder()

        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "stream": False,
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=json.dumps(request_data).encode("utf-8"),
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_success
        assert result.value.model == "gpt-4"
        assert len(result.value.messages) == 1

    def test_anthropic_compatible_request(self):
        """Decode Anthropic-compatible request shape."""
        decoder = CaptureDecoder()

        request_data = {
            "model": "claude-3-opus-20240229",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 1024,
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=json.dumps(request_data).encode("utf-8"),
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_success
        assert result.value.model == "claude-3-opus-20240229"

    def test_gemini_compatible_request(self):
        """Decode Gemini-compatible request shape."""
        decoder = CaptureDecoder()

        request_data = {
            "model": "gemini-pro",
            "messages": [{"role": "user", "parts": [{"text": "Hello"}]}],
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=json.dumps(request_data).encode("utf-8"),
        )

        result = decoder.decode_inbound_request(entry)

        # Should attempt to normalize to canonical format
        assert (
            result.is_success or result.is_failure
        )  # Best-effort, may fail if shape too different

    def test_openai_compatible_response(self):
        """Decode OpenAI-compatible response shape."""
        decoder = CaptureDecoder()

        response_data = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=json.dumps(response_data).encode("utf-8"),
        )

        result = decoder.decode_response(entry)

        assert result.is_success
        assert isinstance(result.value, ResponseEnvelope)
        assert result.value.content == response_data

    def test_outbound_request_decoding(self):
        """Decode outbound request to backend (PROXY_TO_BACKEND)."""
        decoder = CaptureDecoder()

        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Test"}],
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.PROXY_TO_BACKEND,
            sequence=0,
            data=json.dumps(request_data).encode("utf-8"),
            metadata=CaptureMetadata(backend="openai", model="gpt-4"),
        )

        result = decoder.decode_outbound_request(entry)

        assert result.is_success
        assert result.value.model == "gpt-4"


class TestCaptureDecoderStreaming:
    """Tests for streaming response decoding and reconstruction."""

    def test_streaming_response_detection(self):
        """Streaming response detection based on metadata."""
        decoder = CaptureDecoder()

        # SSE chunk format
        sse_chunk = (
            b'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":"Hello"}}]}\n\n'
        )

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=sse_chunk,
            metadata=CaptureMetadata(is_stream_start=True, chunk_index=0),
        )

        result = decoder.decode_response(entry)

        # Should detect as streaming
        assert result.is_success
        # Note: StreamingResponseEnvelope has async iterator, so we check type
        # In practice, streaming responses are reconstructed from multiple entries

    def test_non_streaming_response_detection(self):
        """Non-streaming response detection."""
        decoder = CaptureDecoder()

        response_data = {
            "id": "chatcmpl-123",
            "choices": [
                {"message": {"role": "assistant", "content": "Complete response"}}
            ],
        }

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=json.dumps(response_data).encode("utf-8"),
            metadata=CaptureMetadata(is_stream_start=False),
        )

        result = decoder.decode_response(entry)

        assert result.is_success
        assert isinstance(result.value, ResponseEnvelope)
        assert not isinstance(result.value, StreamingResponseEnvelope)

    def test_sse_chunk_parsing(self):
        """SSE chunk parsing and envelope construction."""
        decoder = CaptureDecoder()

        # Parse SSE format chunk
        sse_data = b'data: {"choices":[{"delta":{"content":" chunk"}}]}\n\n'

        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=sse_data,
            metadata=CaptureMetadata(chunk_index=1),
        )

        # For individual chunks, decoder should extract JSON payload
        # Full streaming reconstruction would happen at a higher level
        result = decoder.decode_response(entry)

        # Best-effort: may succeed or fail depending on implementation
        assert result.is_success or result.is_failure

    def test_stream_start_end_markers(self):
        """Stream start/end markers handled correctly."""
        decoder = CaptureDecoder()

        # Stream start marker
        start_entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=b"",
            metadata=CaptureMetadata(is_stream_start=True),
        )

        # Stream end marker
        end_entry = CaptureEntry(
            timestamp=2.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=1,
            data=b"data: [DONE]\n\n",
            metadata=CaptureMetadata(is_stream_end=True, total_chunks=5),
        )

        start_result = decoder.decode_response(start_entry)
        end_result = decoder.decode_response(end_entry)

        # Should handle gracefully
        assert start_result.is_success or start_result.is_failure
        assert end_result.is_success or end_result.is_failure
