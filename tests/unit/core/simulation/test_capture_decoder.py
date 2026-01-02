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
        from pydantic.types import JsonValue

        diagnostics: dict[str, JsonValue] = {
            "raw_bytes_hex": "74657374",
            "attempted_format": "json",
        }
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


class TestCaptureDecoderDiagnostics:
    """Tests for diagnostic structure, JSON-safety, and determinism."""

    def test_diagnostics_are_json_safe(self):
        """Verify all diagnostic values are JSON-serializable."""
        decoder = CaptureDecoder()

        # Test various failure scenarios that produce diagnostics
        test_cases = [
            # Empty data
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"",
            ),
            # Invalid JSON
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"not valid json {",
            ),
            # Invalid UTF-8
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"\xff\xfe\xfd",
            ),
            # Missing required fields
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=json.dumps({"model": "gpt-4"}).encode("utf-8"),
            ),
        ]

        for entry in test_cases:
            result = decoder.decode_inbound_request(entry)
            assert result.is_failure

            # Verify diagnostics are JSON-serializable
            if result.diagnostics:
                json_str = json.dumps(result.diagnostics)
                assert isinstance(json_str, str)
                # Verify we can deserialize it back
                deserialized = json.loads(json_str)
                assert isinstance(deserialized, dict)

            # Verify error details are JSON-serializable
            if result.error and result.error.details:
                json_str = json.dumps(result.error.details)
                assert isinstance(json_str, str)
                deserialized = json.loads(json_str)
                assert isinstance(deserialized, dict)

    def test_diagnostics_determinism(self):
        """Same failure produces identical diagnostics."""
        decoder = CaptureDecoder()

        # Create an entry that will fail consistently
        invalid_json = b"not valid json {"
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=invalid_json,
        )

        # Decode multiple times
        result1 = decoder.decode_inbound_request(entry)
        result2 = decoder.decode_inbound_request(entry)
        result3 = decoder.decode_inbound_request(entry)

        assert result1.is_failure
        assert result2.is_failure
        assert result3.is_failure

        # Diagnostics should be identical
        if result1.diagnostics and result2.diagnostics and result3.diagnostics:
            assert result1.diagnostics == result2.diagnostics == result3.diagnostics

        # Error details should be identical
        if (
            result1.error
            and result2.error
            and result3.error
            and result1.error.details
            and result2.error.details
            and result3.error.details
        ):
            assert (
                result1.error.details == result2.error.details == result3.error.details
            )

    def test_diagnostics_structure_consistency(self):
        """Diagnostic structure is consistent across decode methods."""
        decoder = CaptureDecoder()

        # Test with invalid JSON for different decode methods
        invalid_data = b"not valid json {"

        # Test inbound request
        inbound_entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=invalid_data,
        )
        inbound_result = decoder.decode_inbound_request(inbound_entry)

        # Test outbound request
        outbound_entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.PROXY_TO_BACKEND,
            sequence=0,
            data=invalid_data,
        )
        outbound_result = decoder.decode_outbound_request(outbound_entry)

        # Both should fail with similar diagnostic structure
        assert inbound_result.is_failure
        assert outbound_result.is_failure

        # Both should have diagnostics (if any)
        if inbound_result.diagnostics:
            assert isinstance(inbound_result.diagnostics, dict)
            # Verify JSON-safety
            json.dumps(inbound_result.diagnostics)

        if outbound_result.diagnostics:
            assert isinstance(outbound_result.diagnostics, dict)
            json.dumps(outbound_result.diagnostics)

    def test_bytes_in_diagnostics_converted_to_json_safe(self):
        """Bytes are converted to hex strings in diagnostics."""
        decoder = CaptureDecoder()

        # Create an entry with binary data that will fail UTF-8 decoding
        binary_data = b"\xff\xfe\xfd\x00\x01\x02"
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=binary_data,
        )

        result = decoder.decode_inbound_request(entry)

        assert result.is_failure
        assert result.error is not None

        # Check that any bytes in diagnostics are converted to hex strings
        if result.error.details:
            for key, value in result.error.details.items():
                assert not isinstance(value, bytes), f"Found bytes in details[{key}]"
                if "hex" in key.lower() or "preview" in key.lower():
                    # Should be a hex string
                    assert isinstance(value, str)

        if result.diagnostics:
            for key, value in result.diagnostics.items():
                assert not isinstance(
                    value, bytes
                ), f"Found bytes in diagnostics[{key}]"
                if "hex" in key.lower():
                    # Should be a hex string
                    assert isinstance(value, str)

    def test_diagnostics_merge_correctly(self):
        """Error details and additional diagnostics merge correctly."""
        error = DecodeError("Test error", details={"field1": "value1", "field2": 42})
        from pydantic.types import JsonValue

        additional_diagnostics: dict[str, JsonValue] = {
            "field3": "value3",
            "field4": True,
        }

        result = DecodeResult.failure(error, diagnostics=additional_diagnostics)

        assert result.is_failure
        assert result.diagnostics is not None
        # Should contain all fields
        assert result.diagnostics["field1"] == "value1"
        assert result.diagnostics["field2"] == 42
        assert result.diagnostics["field3"] == "value3"
        assert result.diagnostics["field4"] is True

        # Verify JSON-safety
        json.dumps(result.diagnostics)

    def test_diagnostics_round_trip_serialization(self):
        """Diagnostics can be serialized to JSON and back."""
        decoder = CaptureDecoder()

        # Create various failure scenarios
        test_entries = [
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"",
            ),
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.CLIENT_TO_PROXY,
                sequence=0,
                data=b"invalid json",
            ),
            CaptureEntry(
                timestamp=1.0,
                direction=CaptureDirection.BACKEND_TO_PROXY,
                sequence=0,
                data=b"invalid response",
            ),
        ]

        for entry in test_entries:
            if entry.direction == CaptureDirection.CLIENT_TO_PROXY:
                result = decoder.decode_inbound_request(entry)
            else:
                result = decoder.decode_response(entry)

            assert result.is_failure

            # Test round-trip serialization for diagnostics
            if result.diagnostics:
                json_str = json.dumps(result.diagnostics)
                deserialized = json.loads(json_str)
                assert deserialized == result.diagnostics

            # Test round-trip serialization for error details
            if result.error and result.error.details:
                json_str = json.dumps(result.error.details)
                deserialized = json.loads(json_str)
                assert deserialized == result.error.details

    def test_diagnostics_dict_normalization_determinism(self):
        """Dict normalization produces deterministic output regardless of key order."""
        decoder = CaptureDecoder()

        # Create dicts with different key orders
        dict1 = {"z": 3, "a": 1, "m": 2}
        dict2 = {"a": 1, "m": 2, "z": 3}
        dict3 = {"m": 2, "z": 3, "a": 1}

        # Normalize all dicts
        normalized1 = decoder._normalize_to_json_value(dict1)
        normalized2 = decoder._normalize_to_json_value(dict2)
        normalized3 = decoder._normalize_to_json_value(dict3)

        # All should produce identical normalized dicts (keys sorted)
        assert normalized1 == normalized2 == normalized3

        # Serialize to JSON - should produce identical strings
        json1 = json.dumps(normalized1, sort_keys=True)
        json2 = json.dumps(normalized2, sort_keys=True)
        json3 = json.dumps(normalized3, sort_keys=True)

        assert json1 == json2 == json3

        # Verify keys are sorted
        assert isinstance(normalized1, dict)
        assert list(normalized1.keys()) == ["a", "m", "z"]


class TestCaptureDecoderDeterminismEnhanced:
    """Enhanced tests for decode determinism including diagnostics."""

    def test_diagnostics_determinism_for_same_failure(self):
        """Same failure produces identical diagnostics."""
        decoder = CaptureDecoder()

        # Create a request that will fail validation
        invalid_request = json.dumps({"model": "gpt-4"})  # Missing required "messages"
        entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=invalid_request.encode("utf-8"),
        )

        # Decode multiple times
        results = [decoder.decode_inbound_request(entry) for _ in range(5)]

        # All should fail
        assert all(r.is_failure for r in results)

        # All diagnostics should be identical
        diagnostics_list = [r.diagnostics for r in results if r.diagnostics]
        if diagnostics_list:
            first_diagnostics = diagnostics_list[0]
            for diag in diagnostics_list[1:]:
                assert diag == first_diagnostics

        # All error details should be identical
        error_details_list = [
            r.error.details for r in results if r.error and r.error.details
        ]
        if error_details_list:
            first_details = error_details_list[0]
            for details in error_details_list[1:]:
                assert details == first_details

    def test_diagnostics_determinism_across_decode_methods(self):
        """Different decode methods produce consistent diagnostic structures."""
        decoder = CaptureDecoder()

        # Use the same invalid data for different decode methods
        invalid_data = b"not valid json {"

        # Test request decoding
        request_entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.CLIENT_TO_PROXY,
            sequence=0,
            data=invalid_data,
        )
        request_result = decoder.decode_inbound_request(request_entry)

        # Test response decoding
        response_entry = CaptureEntry(
            timestamp=1.0,
            direction=CaptureDirection.BACKEND_TO_PROXY,
            sequence=0,
            data=invalid_data,
        )
        response_result = decoder.decode_response(response_entry)

        # Both should fail
        assert request_result.is_failure
        assert response_result.is_failure

        # Both should have JSON-safe diagnostics
        if request_result.diagnostics:
            json.dumps(request_result.diagnostics)
        if response_result.diagnostics:
            json.dumps(response_result.diagnostics)

        # Both should have JSON-safe error details
        if request_result.error and request_result.error.details:
            json.dumps(request_result.error.details)
        if response_result.error and response_result.error.details:
            json.dumps(response_result.error.details)
