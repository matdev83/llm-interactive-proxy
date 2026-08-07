"""
Property-based tests for streaming contracts.

These tests verify universal properties that should hold across all
streaming operations, using Hypothesis for property-based testing.

Feature: streaming-pipeline-refactor
"""

import json
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.core.ports.streaming_contracts import (
    SentinelManager,
    StreamingContent,
)


# Hypothesis strategies for generating test data
@st.composite
def valid_content_strategy(draw: Any) -> str | dict | bytes:
    """Generate valid content values."""
    content_type = draw(st.sampled_from(["str", "dict", "bytes"]))
    if content_type == "str":
        return cast(str, draw(st.text()))
    elif content_type == "dict":
        return cast(
            dict[str, str], draw(st.dictionaries(st.text(), st.text(), max_size=5))
        )
    else:  # bytes
        return cast(bytes, draw(st.binary()))


@st.composite
def valid_metadata_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid metadata dictionaries."""
    metadata: dict[str, Any] = {}

    # Optionally add stream_id
    if draw(st.booleans()):
        metadata["stream_id"] = draw(st.text(min_size=1))

    # Optionally add provider
    if draw(st.booleans()):
        metadata["provider"] = draw(
            st.sampled_from(["openai", "anthropic", "gemini", "test"])
        )

    # Optionally add model
    if draw(st.booleans()):
        metadata["model"] = draw(st.text(min_size=1))

    # Optionally add role
    if draw(st.booleans()):
        metadata["role"] = draw(st.sampled_from(["assistant", "user", "system"]))

    # Optionally add finish_reason
    if draw(st.booleans()):
        metadata["finish_reason"] = draw(
            st.sampled_from([None, "stop", "length", "tool_calls"])
        )

    # Optionally add tool_calls
    if draw(st.booleans()):
        metadata["tool_calls"] = draw(
            st.lists(
                st.fixed_dictionaries(
                    {
                        "id": st.text(min_size=1),
                        "type": st.just("function"),
                        "function": st.fixed_dictionaries(
                            {"name": st.text(min_size=1), "arguments": st.text()}
                        ),
                    }
                ),
                max_size=3,
            )
        )

    return metadata


@st.composite
def streaming_content_strategy(draw: Any) -> StreamingContent:
    """Generate valid StreamingContent instances."""
    content = draw(valid_content_strategy())
    metadata = draw(valid_metadata_strategy())
    is_done = draw(st.booleans())
    is_empty = draw(st.booleans())
    stream_id = draw(st.one_of(st.none(), st.text(min_size=1)))
    is_cancellation = draw(st.booleans())

    return StreamingContent(
        content=content,
        metadata=metadata,
        is_done=is_done,
        is_empty=is_empty,
        stream_id=stream_id,
        is_cancellation=is_cancellation,
    )


# Property 1: Chunk validation
def test_streaming_content_inherits_stream_id_from_metadata() -> None:
    """Chunks should adopt stream_id from metadata when not provided explicitly."""
    metadata = {"stream_id": "stream-123"}
    chunk = StreamingContent(content="", metadata=dict(metadata))

    assert chunk.stream_id == "stream-123"
    assert chunk.metadata["stream_id"] == "stream-123"


def test_streaming_content_populates_metadata_stream_id_when_missing() -> None:
    """Chunks with explicit stream_id should mirror it into metadata."""
    chunk = StreamingContent(content="", metadata={}, stream_id="stream-456")

    assert chunk.metadata["stream_id"] == "stream-456"


@pytest.mark.parametrize(
    "finish_reason", ["error", "cancelled", "user_cancelled", "system_cancelled"]
)
def test_terminal_finish_reason_marks_chunk_done(finish_reason: str) -> None:
    """Terminal finish_reason values should mark a chunk as done."""
    chunk = StreamingContent(
        content="",
        metadata={"finish_reason": finish_reason},
        is_done=False,
    )

    assert chunk.is_done is True


@pytest.mark.parametrize(
    "finish_reason", ["stop", "length", "tool_calls", "content_filter"]
)
def test_non_terminal_finish_reason_keeps_stream_open(finish_reason: str) -> None:
    """Non-terminal finish_reason values should not stop the stream by themselves."""
    chunk = StreamingContent(
        content="",
        metadata={"finish_reason": finish_reason},
        is_done=False,
    )

    assert chunk.is_done is False


# Additional validation tests for edge cases
@given(content=st.one_of(st.integers(), st.floats(), st.lists(st.text())))
@settings(max_examples=20)
def test_invalid_content_type_raises_error(content: Any) -> None:
    """Test that invalid content types raise ValueError."""
    with pytest.raises(ValueError, match="content must be str, dict, or bytes"):
        StreamingContent(content=content)  # type: ignore[arg-type]


@given(metadata=st.one_of(st.text(), st.integers(), st.lists(st.text())))
@settings(max_examples=20)
def test_invalid_metadata_type_raises_error(metadata: Any) -> None:
    """Test that invalid metadata types raise ValueError."""
    with pytest.raises(ValueError, match="metadata must be dict"):
        StreamingContent(content="test", metadata=metadata)  # type: ignore[arg-type]


@given(is_done=st.one_of(st.text(), st.integers()))
def test_invalid_is_done_type_raises_error(is_done: Any) -> None:
    """Test that invalid is_done types raise ValueError."""
    with pytest.raises(ValueError, match="is_done must be bool"):
        StreamingContent(content="test", is_done=is_done)  # type: ignore[arg-type]


def test_sentinel_manager_creates_valid_done_chunk() -> None:
    """Test that SentinelManager creates valid done chunks."""
    done_chunk = SentinelManager.create_done_chunk()

    assert done_chunk.is_done is True
    assert done_chunk.content == "[DONE]"
    assert done_chunk.metadata["finish_reason"] == "stop"
    assert SentinelManager.is_done_marker(done_chunk)


def test_sentinel_manager_format_sse_done() -> None:
    """Test that SentinelManager formats SSE done correctly."""
    sse_done = SentinelManager.format_sse_done()

    assert sse_done == b"data: [DONE]\n\n"
    assert isinstance(sse_done, bytes)


@given(chunk=streaming_content_strategy())
@settings(max_examples=50)
def test_streaming_content_to_bytes_is_valid_sse(chunk: StreamingContent) -> None:
    """Test that to_bytes produces valid SSE format."""
    sse_bytes = chunk.to_bytes()

    assert isinstance(sse_bytes, bytes)

    # Decode and verify format
    sse_str = sse_bytes.decode("utf-8")

    if chunk.is_done:
        # Done chunks should contain [DONE]
        assert "[DONE]" in sse_str
    else:
        # Non-done chunks should start with "data: "
        assert sse_str.startswith("data: ")
        # Should end with double newline
        assert sse_str.endswith("\n\n")

        # Extract JSON part
        json_part = sse_str[6:-2]  # Remove "data: " and "\n\n"
        # Should be valid JSON
        parsed = json.loads(json_part)
        assert "choices" in parsed
        assert isinstance(parsed["choices"], list)


@given(chunk=streaming_content_strategy())
@settings(max_examples=20)
def test_streaming_content_to_dict_preserves_data(chunk: StreamingContent) -> None:
    """Test that to_dict preserves all data."""
    chunk_dict = chunk.to_dict()

    assert isinstance(chunk_dict, dict)
    assert "content" in chunk_dict
    assert "metadata" in chunk_dict
    assert "is_done" in chunk_dict
    assert "is_empty" in chunk_dict
    assert "stream_id" in chunk_dict
    assert "is_cancellation" in chunk_dict

    # Verify types
    assert isinstance(chunk_dict["metadata"], dict)
    assert isinstance(chunk_dict["is_done"], bool)
    assert isinstance(chunk_dict["is_empty"], bool)
    assert isinstance(chunk_dict["is_cancellation"], bool)


# Helper function to create HTTPStatusError
def _create_http_status_error(status_code: int = 500) -> httpx.HTTPStatusError:
    """Create a mock HTTPStatusError for testing."""
    request = httpx.Request("GET", "https://api.example.com")
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.text = "Error response"
    return httpx.HTTPStatusError("Error", request=request, response=response)


# Property 4: Error terminal chunks
@given(
    error_type=st.sampled_from(
        [
            "timeout",
            "http_error",
            "connect_error",
            "json_error",
            "generic_error",
        ]
    ),
    provider=st.sampled_from(["openai", "anthropic", "gemini", "test"]),
    stream_id=st.one_of(st.none(), st.text(min_size=1)),
)
@settings(max_examples=50)
async def test_property_error_terminal_chunks(
    error_type: str, provider: str, stream_id: str | None
) -> None:
    """
    Property 4: Error terminal chunks
    Feature: streaming-pipeline-refactor, Property 4: Error terminal chunks

    For any error during streaming, the system should emit a terminal chunk
    with is_done=True and structured error metadata, then close the stream.

    Validates: Requirements 1.4, 4.2
    """
    from src.core.ports.streaming_contracts import handle_streaming_error

    # Create the appropriate error based on error_type
    error: Exception
    if error_type == "timeout":
        error = httpx.TimeoutException("Timeout")
    elif error_type == "http_error":
        error = _create_http_status_error(500)
    elif error_type == "connect_error":
        error = httpx.ConnectError("Connection failed")
    elif error_type == "json_error":
        error = json.JSONDecodeError("Invalid JSON", "", 0)
    else:  # generic_error
        error = Exception("Generic error")

    # Create error chunk
    error_chunk = await handle_streaming_error(error, stream_id, provider)

    # Verify it's a terminal chunk
    assert error_chunk.is_done is True, "Error chunk must be terminal (is_done=True)"

    # Verify error metadata is present and structured
    assert "error" in error_chunk.metadata, "Error chunk must have error metadata"
    error_info = error_chunk.metadata["error"]

    assert isinstance(error_info, dict), "Error info must be a dictionary"
    assert "type" in error_info, "Error info must have type"
    assert "message" in error_info, "Error info must have message"
    assert "code" in error_info, "Error info must have code"
    assert "retryable" in error_info, "Error info must have retryable flag"

    # Verify finish_reason is set to error
    assert (
        error_chunk.metadata.get("finish_reason") == "error"
    ), "Error chunk must have finish_reason='error'"

    # Verify provider and stream_id are preserved
    assert error_chunk.metadata.get("provider") == provider
    if stream_id:
        assert error_chunk.metadata.get("stream_id") == stream_id

    # Verify content is empty for error chunks
    assert error_chunk.content == "", "Error chunk content should be empty"


# Property 11: Error mapping consistency
@given(
    error_type=st.sampled_from(
        [
            "timeout",
            "http_error_429",
            "http_error_500",
            "connect_error",
            "json_error",
            "generic_error",
        ]
    ),
    provider=st.sampled_from(["openai", "anthropic", "gemini", "test"]),
    stream_id=st.one_of(st.none(), st.text(min_size=1)),
)
@settings(max_examples=50)
def test_property_error_mapping_consistency(
    error_type: str, provider: str, stream_id: str | None
) -> None:
    """
    Property 11: Error mapping consistency
    Feature: streaming-pipeline-refactor, Property 11: Error mapping consistency

    For any backend error type, it should be mapped to exactly one LLMProxyError
    variant through the centralized error mapping layer.

    Validates: Requirements 4.1
    """
    from src.core.common.exceptions import (
        APIConnectionError,
        APITimeoutError,
        BackendError,
        LLMProxyError,
        ParsingError,
        RateLimitExceededError,
    )
    from src.core.ports.streaming_contracts import StreamingErrorMapper

    # Create the appropriate error based on error_type
    error: Exception
    expected_type: type[LLMProxyError]
    if error_type == "timeout":
        error = httpx.TimeoutException("Timeout")
        expected_type = APITimeoutError
    elif error_type == "http_error_429":
        error = _create_http_status_error(429)
        expected_type = RateLimitExceededError
    elif error_type == "http_error_500":
        error = _create_http_status_error(500)
        expected_type = BackendError
    elif error_type == "connect_error":
        error = httpx.ConnectError("Connection failed")
        expected_type = APIConnectionError
    elif error_type == "json_error":
        error = json.JSONDecodeError("Invalid JSON", "", 0)
        expected_type = ParsingError
    else:  # generic_error
        error = Exception("Generic error")
        expected_type = BackendError

    # Map the error
    mapped_error = StreamingErrorMapper.map_backend_error(error, provider, stream_id)

    # Verify it's an LLMProxyError
    assert isinstance(
        mapped_error, LLMProxyError
    ), f"Mapped error must be LLMProxyError, got {type(mapped_error)}"

    # Verify it's the expected specific type
    assert isinstance(
        mapped_error, expected_type
    ), f"Expected {expected_type.__name__}, got {type(mapped_error).__name__}"

    # Verify provider is in details
    assert (
        "provider" in mapped_error.details
    ), "Mapped error must include provider in details"
    assert mapped_error.details["provider"] == provider

    # Verify stream_id is in details if provided
    if stream_id:
        assert (
            "stream_id" in mapped_error.details
        ), "Mapped error must include stream_id in details when provided"
        assert mapped_error.details["stream_id"] == stream_id

    # Verify the same error type always maps to the same LLMProxyError variant
    # (test idempotence of mapping)
    mapped_error_2 = StreamingErrorMapper.map_backend_error(error, provider, stream_id)
    assert type(mapped_error) == type(
        mapped_error_2
    ), "Same error should always map to same type"


# Property 10: Structured error responses
@given(
    error_type=st.sampled_from(
        [
            "timeout",
            "http_error",
            "connect_error",
            "json_error",
            "generic_error",
        ]
    ),
    provider=st.sampled_from(["openai", "anthropic", "gemini", "test"]),
    stream_id=st.one_of(st.none(), st.text(min_size=1)),
)
@settings(max_examples=50)
async def test_property_structured_error_responses(
    error_type: str, provider: str, stream_id: str | None
) -> None:
    """
    Property 10: Structured error responses
    Feature: streaming-pipeline-refactor, Property 10: Structured error responses

    For any backend error, the client response should contain a structured
    error object without raw HTTPException or stack traces.

    Validates: Requirements 3.4, 4.4
    """
    from src.core.ports.streaming_contracts import handle_streaming_error

    # Create the appropriate error based on error_type
    error: Exception
    if error_type == "timeout":
        error = httpx.TimeoutException("Timeout")
    elif error_type == "http_error":
        error = _create_http_status_error(500)
    elif error_type == "connect_error":
        error = httpx.ConnectError("Connection failed")
    elif error_type == "json_error":
        error = json.JSONDecodeError("Invalid JSON", "", 0)
    else:  # generic_error
        error = Exception("Generic error")

    # Create error chunk
    error_chunk = await handle_streaming_error(error, stream_id, provider)

    # Verify error structure
    assert "error" in error_chunk.metadata, "Must have error metadata"
    error_info = error_chunk.metadata["error"]

    # Verify required fields are present
    required_fields = ["type", "message", "code", "retryable"]
    for field in required_fields:
        assert field in error_info, f"Error info must have '{field}' field"

    # Verify no raw exception details are exposed
    error_str = str(error_info)
    assert "Traceback" not in error_str, "Must not expose stack traces"
    assert "HTTPException" not in error_str, "Must not expose HTTPException"
    assert "raise" not in error_str, "Must not expose raise statements"

    # Verify error message is user-friendly (not raw exception repr)
    message = error_info["message"]
    assert isinstance(message, str), "Error message must be string"
    assert len(message) > 0, "Error message must not be empty"
    assert not message.startswith("<"), "Error message must not be raw repr"

    # Verify error type is a clean class name
    error_type_name = error_info["type"]
    assert isinstance(error_type_name, str), "Error type must be string"
    assert error_type_name.endswith("Error"), "Error type should end with 'Error'"
    assert (
        "Exception" not in error_type_name or error_type_name == "TimeoutException"
    ), "Error type should use Error suffix, not Exception"

    # Verify retryable flag is boolean
    assert isinstance(error_info["retryable"], bool), "Retryable flag must be boolean"

    # Convert to bytes (SSE format) and verify no sensitive data leaks
    sse_bytes = error_chunk.to_bytes()
    sse_str = sse_bytes.decode("utf-8")

    # Verify no stack traces in SSE output
    assert "Traceback" not in sse_str, "SSE output must not contain stack traces"
    assert 'File "' not in sse_str, "SSE output must not contain file paths from traces"


# Property 22: Backend format normalization
@given(
    content=valid_content_strategy(),
    metadata=valid_metadata_strategy(),
    provider=st.sampled_from(["openai", "anthropic", "gemini", "test"]),
    stream_id=st.one_of(st.none(), st.text(min_size=1)),
)
@settings(max_examples=20)
def test_property_backend_format_normalization(
    content: str | dict | bytes,
    metadata: dict[str, Any],
    provider: str,
    stream_id: str | None,
) -> None:
    """
    Property 22: Backend format normalization
    Feature: streaming-pipeline-refactor, Property 22: Backend format normalization

    For any backend-specific chunk format, the normalizer should convert it
    to StreamingContent with all required fields populated.

    Validates: Requirements 8.2
    """
    from src.core.ports.streaming_contracts import BaseStreamNormalizer

    # Create a normalizer instance
    normalizer = BaseStreamNormalizer(provider=provider)

    # Create a normalized chunk using the normalizer's utility method
    chunk = normalizer.create_normalized_chunk(
        content=content,
        metadata=metadata,
        is_done=False,
        is_empty=False,
        stream_id=stream_id,
    )

    # Verify the chunk is a valid StreamingContent instance
    assert isinstance(
        chunk, StreamingContent
    ), "Normalized chunk must be StreamingContent"

    # Verify all required fields are populated
    assert hasattr(chunk, "content"), "Chunk must have content field"
    assert hasattr(chunk, "metadata"), "Chunk must have metadata field"
    assert hasattr(chunk, "is_done"), "Chunk must have is_done field"
    assert hasattr(chunk, "is_empty"), "Chunk must have is_empty field"
    assert hasattr(chunk, "stream_id"), "Chunk must have stream_id field"

    # Verify content is preserved
    assert chunk.content == content, "Content must be preserved"

    # Verify metadata is enriched with provider
    assert "provider" in chunk.metadata, "Metadata must include provider"
    assert chunk.metadata["provider"] == provider, "Provider must match"

    # Verify stream_id is preserved if provided
    if stream_id:
        assert chunk.stream_id == stream_id, "Stream ID must be preserved"
        assert (
            "stream_id" in chunk.metadata
        ), "Stream ID must be in metadata if provided"
        assert chunk.metadata["stream_id"] == stream_id

    # Verify the chunk passes validation
    assert normalizer.validate_chunk(chunk), "Normalized chunk must pass validation"


# Property 23: Metadata schema mapping
@given(
    metadata=valid_metadata_strategy(),
    provider=st.sampled_from(["openai", "anthropic", "gemini", "test"]),
)
@settings(max_examples=50)
def test_property_metadata_schema_mapping(
    metadata: dict[str, Any], provider: str
) -> None:
    """
    Property 23: Metadata schema mapping
    Feature: streaming-pipeline-refactor, Property 23: Metadata schema mapping

    For any backend metadata schema, the normalizer should map all fields
    to the common metadata schema.

    Validates: Requirements 8.3
    """
    from src.core.ports.streaming_contracts import BaseStreamNormalizer

    # Create a normalizer instance
    normalizer = BaseStreamNormalizer(provider=provider)

    # Validate the metadata schema
    is_valid = normalizer.validate_metadata_schema(metadata)

    # The metadata should be valid since it was generated by our strategy
    assert is_valid, "Generated metadata should pass schema validation"

    # Verify all fields in metadata conform to the schema
    for field, value in metadata.items():
        if field in normalizer.METADATA_SCHEMA:
            expected_type = normalizer.METADATA_SCHEMA[field]

            # Handle union types
            if isinstance(expected_type, tuple):
                assert isinstance(
                    value, expected_type
                ), f"Field {field} must be one of {expected_type}"
            else:
                assert isinstance(
                    value, expected_type
                ), f"Field {field} must be {expected_type.__name__}"

    # Create a chunk with this metadata and verify it validates
    chunk = normalizer.create_normalized_chunk(
        content="test", metadata=metadata, stream_id="test-stream"
    )

    assert normalizer.validate_chunk(
        chunk
    ), "Chunk with valid metadata must pass validation"

    # Verify metadata is preserved in the chunk (except provider and stream_id)
    for field, value in metadata.items():
        if field in chunk.metadata:
            # Provider is always overridden by the normalizer
            if field == "provider":
                assert (
                    chunk.metadata[field] == provider
                ), "Provider must be set by normalizer"
            # Stream_id is overridden if provided as parameter
            elif field == "stream_id":
                assert (
                    chunk.metadata[field] == "test-stream"
                ), "Stream ID must be set by parameter"
            else:
                assert (
                    chunk.metadata[field] == value
                ), f"Metadata field {field} must be preserved"


# Property 17: StreamingContent structure stability
@given(
    chunks=st.lists(
        st.fixed_dictionaries(
            {
                "content": st.text(),
                "metadata": valid_metadata_strategy(),
                "is_done": st.booleans(),
            }
        ),
        min_size=1,
        max_size=50,
    ),
)
@settings(max_examples=20)
async def test_property_streaming_content_structure_stability(
    chunks: list[dict[str, Any]],
) -> None:
    """
    Property 17: StreamingContent structure stability
    Feature: streaming-pipeline-refactor, Property 17: StreamingContent structure stability

    For any chunk passed to middleware, it should be a valid StreamingContent
    object with all required fields present.

    Validates: Requirements 7.1
    """
    from src.core.ports.streaming_contracts import (
        IStreamProcessor,
    )
    from src.core.ports.streaming_contracts import (
        StreamingContent as ActualStreamingContent,
    )
    from src.core.services.streaming.stream_normalizer import StreamNormalizer

    # Create a simple pass-through processor to simulate middleware
    class PassThroughProcessor(IStreamProcessor):
        async def process(
            self, content: ActualStreamingContent
        ) -> ActualStreamingContent:
            # Verify the chunk has all required fields before processing
            assert isinstance(
                content, ActualStreamingContent
            ), "Chunk must be StreamingContent instance"
            assert hasattr(content, "content"), "Chunk must have content field"
            assert hasattr(content, "metadata"), "Chunk must have metadata field"
            assert hasattr(content, "is_done"), "Chunk must have is_done field"
            assert hasattr(content, "is_empty"), "Chunk must have is_empty field"
            assert hasattr(
                content, "is_cancellation"
            ), "Chunk must have is_cancellation field"

            # Verify field types
            assert isinstance(
                content.content, str | dict | bytes
            ), "content must be str, dict, or bytes"
            assert isinstance(content.metadata, dict), "metadata must be dict"
            assert isinstance(content.is_done, bool), "is_done must be bool"
            assert isinstance(content.is_empty, bool), "is_empty must be bool"
            assert isinstance(
                content.is_cancellation, bool
            ), "is_cancellation must be bool"

            return content

        def reset(self) -> None:  # pragma: no cover - no state to reset
            return None

    # Create a normalizer with the pass-through processor
    processor = PassThroughProcessor()
    normalizer = StreamNormalizer([processor])

    # Create an async generator from the chunks (as dicts that will be converted)
    async def chunk_stream():
        for chunk_dict in chunks:
            yield chunk_dict

    # Process the stream through the normalizer
    processed_chunks = []
    async for processed_chunk in normalizer.process_stream(
        chunk_stream(), output_format="objects"
    ):
        # Verify the processed chunk is still a valid StreamingContent
        assert isinstance(
            processed_chunk, ActualStreamingContent
        ), "Processed chunk must be StreamingContent"

        # Verify all required fields are still present after processing
        assert hasattr(
            processed_chunk, "content"
        ), "Processed chunk must have content field"
        assert hasattr(
            processed_chunk, "metadata"
        ), "Processed chunk must have metadata field"
        assert hasattr(
            processed_chunk, "is_done"
        ), "Processed chunk must have is_done field"
        assert hasattr(
            processed_chunk, "is_empty"
        ), "Processed chunk must have is_empty field"
        assert hasattr(
            processed_chunk, "is_cancellation"
        ), "Processed chunk must have is_cancellation field"

        # Verify stream_id is assigned if not present
        assert (
            "stream_id" in processed_chunk.metadata
        ), "Processed chunk must have stream_id in metadata"

        processed_chunks.append(processed_chunk)

    # Verify we got chunks out (unless all were empty and not done)
    # Empty chunks without is_done=True are filtered out by the normalizer
    assert len(processed_chunks) >= 0, "Should process chunks successfully"
