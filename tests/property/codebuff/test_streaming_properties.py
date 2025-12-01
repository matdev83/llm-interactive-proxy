"""
Property-based tests for Codebuff streaming functionality.

Tests Property 11: Chunk conversion
Tests Property 12: User input ID correlation
Validates: Requirements 3.1, 3.2
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from src.codebuff.format_converter import FormatConverter


@given(user_input_id=st.text(min_size=1, max_size=50), text=st.text(max_size=1000))
def test_property_11_chunk_conversion(user_input_id, text):
    """
    Feature: codebuff-backend-compatibility, Property 11: Chunk conversion
    Validates: Requirements 3.1

    For any stream of text chunks from the backend, each chunk should be
    converted to a response-chunk action.
    """
    converter = FormatConverter()

    # Create a response chunk
    chunk_message = converter.create_response_chunk(user_input_id, text)

    # Verify the structure
    assert isinstance(chunk_message, dict), "Chunk message must be a dictionary"
    assert chunk_message["type"] == "action", "Message type must be 'action'"
    assert "data" in chunk_message, "Message must have 'data' field"

    data = chunk_message["data"]
    assert data["type"] == "response-chunk", "Data type must be 'response-chunk'"
    assert "userInputId" in data, "Data must have 'userInputId' field"
    assert "chunk" in data, "Data must have 'chunk' field"
    assert data["userInputId"] == user_input_id, "User input ID must match"
    assert data["chunk"] == text, "Chunk text must match"


@given(
    user_input_id=st.text(min_size=1, max_size=50),
    chunks=st.lists(st.text(max_size=100), min_size=1, max_size=20),
)
def test_property_12_user_input_id_correlation(user_input_id, chunks):
    """
    Feature: codebuff-backend-compatibility, Property 12: User input ID correlation
    Validates: Requirements 3.2

    For any request with a user input ID, all response chunks should include
    that same user input ID.
    """
    converter = FormatConverter()

    # Create multiple chunks for the same request
    chunk_messages = [
        converter.create_response_chunk(user_input_id, chunk) for chunk in chunks
    ]

    # Verify all chunks have the same user input ID
    for chunk_message in chunk_messages:
        data = chunk_message["data"]
        assert (
            data["userInputId"] == user_input_id
        ), f"Expected user input ID {user_input_id}, got {data['userInputId']}"


@given(
    user_input_id=st.text(min_size=1, max_size=50),
    chunks=st.lists(st.text(max_size=100), min_size=1, max_size=20),
)
def test_property_12_chunk_order_preservation(user_input_id, chunks):
    """
    Property 12 extension: Chunk order should be preserved.

    For any sequence of chunks, the order should be maintained when
    converting to response-chunk actions.
    """
    converter = FormatConverter()

    # Create chunks in order
    chunk_messages = [
        converter.create_response_chunk(user_input_id, chunk) for chunk in chunks
    ]

    # Extract chunk text in order
    extracted_chunks = [msg["data"]["chunk"] for msg in chunk_messages]

    # Verify order is preserved
    assert (
        extracted_chunks == chunks
    ), f"Chunk order not preserved: {extracted_chunks} != {chunks}"


@given(
    user_input_id=st.text(min_size=1, max_size=50),
    text=st.text(min_size=0, max_size=1000),
)
def test_property_11_empty_chunk_handling(user_input_id, text):
    """
    Property 11 extension: Empty chunks should be handled correctly.

    For any text including empty strings, the chunk conversion should
    handle it without errors.
    """
    converter = FormatConverter()

    # Create chunk with potentially empty text
    chunk_message = converter.create_response_chunk(user_input_id, text)

    # Verify structure is valid even for empty chunks
    assert chunk_message["type"] == "action"
    assert chunk_message["data"]["type"] == "response-chunk"
    assert chunk_message["data"]["chunk"] == text
    assert isinstance(chunk_message["data"]["chunk"], str)
