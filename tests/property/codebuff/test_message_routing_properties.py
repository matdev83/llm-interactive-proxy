"""Property-based tests for Codebuff message routing.

Feature: codebuff-backend-compatibility
Property 8: JSON parsing
Property 10: Valid message acknowledgment
Validates: Requirements 6.1, 6.5
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.codebuff.message_router import MessageRouter
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating valid JSON data
# ============================================================================


@st.composite
def valid_json_string_strategy(draw: Any) -> str:
    """Generate valid JSON strings.

    This strategy generates JSON strings that should parse successfully.
    """
    # Generate various JSON structures
    json_data = draw(
        st.one_of(
            # Simple values
            st.none(),
            st.booleans(),
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.text(),
            # Complex structures
            st.lists(st.integers(), max_size=10),
            st.dictionaries(st.text(), st.integers(), max_size=10),
            # Nested structures
            st.dictionaries(
                st.text(),
                st.one_of(
                    st.integers(),
                    st.text(),
                    st.lists(st.integers(), max_size=5),
                ),
                max_size=10,
            ),
        )
    )
    return json.dumps(json_data)


@st.composite
def invalid_json_string_strategy(draw: Any) -> str:
    """Generate invalid JSON strings.

    This strategy generates strings that should fail JSON parsing.
    """
    return draw(
        st.one_of(
            # Malformed JSON
            st.just("{invalid}"),
            st.just("[1, 2, 3,]"),  # Trailing comma
            st.just('{"key": value}'),  # Unquoted value
            st.just("{'key': 'value'}"),  # Single quotes
            st.just("{key: 'value'}"),  # Unquoted key
            st.just("[1, 2, 3"),  # Unclosed bracket
            st.just('{"key": "value"'),  # Unclosed brace
            # Not JSON at all
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll"), whitelist_characters=" "
                ),
                min_size=1,
                max_size=50,
            ).filter(lambda x: not x.startswith("{")),
        )
    )


@st.composite
def valid_identify_message_json_strategy(draw: Any) -> str:
    """Generate valid identify message JSON strings."""
    message_data = {
        "type": "identify",
        "txid": draw(st.integers(min_value=0, max_value=1000000)),
        "clientSessionId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
    }
    return json.dumps(message_data)


@st.composite
def valid_ping_message_json_strategy(draw: Any) -> str:
    """Generate valid ping message JSON strings."""
    message_data = {
        "type": "ping",
        "txid": draw(st.integers(min_value=0, max_value=1000000)),
    }
    return json.dumps(message_data)


@st.composite
def valid_subscribe_message_json_strategy(draw: Any) -> str:
    """Generate valid subscribe message JSON strings."""
    message_data = {
        "type": "subscribe",
        "txid": draw(st.integers(min_value=0, max_value=1000000)),
        "topics": draw(
            st.lists(
                st.text(
                    alphabet=st.characters(
                        whitelist_categories=("Lu", "Ll", "Nd"),
                        whitelist_characters="-_/",
                    ),
                    min_size=1,
                    max_size=30,
                ),
                min_size=1,
                max_size=10,
            )
        ),
    }
    return json.dumps(message_data)


@st.composite
def valid_unsubscribe_message_json_strategy(draw: Any) -> str:
    """Generate valid unsubscribe message JSON strings."""
    message_data = {
        "type": "unsubscribe",
        "txid": draw(st.integers(min_value=0, max_value=1000000)),
        "topics": draw(
            st.lists(
                st.text(
                    alphabet=st.characters(
                        whitelist_categories=("Lu", "Ll", "Nd"),
                        whitelist_characters="-_/",
                    ),
                    min_size=1,
                    max_size=30,
                ),
                min_size=1,
                max_size=10,
            )
        ),
    }
    return json.dumps(message_data)


@st.composite
def valid_client_message_json_strategy(draw: Any) -> str:
    """Generate valid client message JSON strings."""
    return draw(
        st.one_of(
            valid_identify_message_json_strategy(),
            valid_ping_message_json_strategy(),
            valid_subscribe_message_json_strategy(),
            valid_unsubscribe_message_json_strategy(),
        )
    )


# ============================================================================
# Property 8: JSON Parsing
# ============================================================================


@given(json_string=valid_json_string_strategy())
@property_test_settings()
def test_property_8_valid_json_parsing(json_string: str) -> None:
    """
    Property 8: JSON Parsing.

    For any valid JSON string, the message router should successfully
    parse it without raising exceptions.

    Validates: Requirements 6.1
    """
    router = MessageRouter()

    # Should parse successfully (no exception raised)
    parsed = router.parse_json(json_string)

    # Verify round-trip consistency
    reparsed = json.loads(json_string)
    assert parsed == reparsed


@given(json_string=invalid_json_string_strategy())
@property_test_settings()
def test_property_8_invalid_json_rejection(json_string: str) -> None:
    """
    Property 8: JSON Parsing - Invalid JSON Rejection.

    For any invalid JSON string, the message router should raise
    a CodebuffMessageError.

    Validates: Requirements 6.1
    """
    from src.codebuff.exceptions import CodebuffMessageError

    router = MessageRouter()

    # Should raise CodebuffMessageError
    try:
        router.parse_json(json_string)
        raise AssertionError(f"Should have rejected invalid JSON: {json_string[:50]}")
    except CodebuffMessageError as e:
        # Verify error contains useful information
        assert "Invalid JSON" in str(e) or "JSON" in str(e)


# ============================================================================
# Property 10: Valid Message Acknowledgment
# ============================================================================


@given(message_json=valid_client_message_json_strategy())
@property_test_settings()
async def test_property_10_valid_message_acknowledgment(message_json: str) -> None:
    """
    Property 10: Valid Message Acknowledgment.

    For any valid message, the system should send an ack message
    with success=true.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was validated successfully

    assert validated_message is not None

    # Verify ack indicates success
    assert ack.type == "ack"
    assert ack.success is True
    assert ack.error is None

    # Verify txid matches
    message_data = json.loads(message_json)
    assert ack.txid == message_data.get("txid")


@given(message_json=valid_identify_message_json_strategy())
@property_test_settings()
async def test_property_10_identify_message_acknowledgment(message_json: str) -> None:
    """
    Property 10: Identify Message Acknowledgment.

    For any valid identify message, the system should send an ack
    with success=true and the correct txid.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was validated successfully

    assert validated_message is not None
    assert validated_message.type == "identify"

    # Verify ack indicates success
    assert ack.success is True
    assert ack.error is None

    # Verify txid matches
    message_data = json.loads(message_json)
    assert ack.txid == message_data["txid"]


@given(message_json=valid_ping_message_json_strategy())
@property_test_settings()
async def test_property_10_ping_message_acknowledgment(message_json: str) -> None:
    """
    Property 10: Ping Message Acknowledgment.

    For any valid ping message, the system should send an ack
    with success=true and the correct txid.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was validated successfully

    assert validated_message is not None
    assert validated_message.type == "ping"

    # Verify ack indicates success
    assert ack.success is True
    assert ack.error is None

    # Verify txid matches
    message_data = json.loads(message_json)
    assert ack.txid == message_data["txid"]


@given(message_json=valid_subscribe_message_json_strategy())
@property_test_settings()
async def test_property_10_subscribe_message_acknowledgment(message_json: str) -> None:
    """
    Property 10: Subscribe Message Acknowledgment.

    For any valid subscribe message, the system should send an ack
    with success=true and the correct txid.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was validated successfully

    assert validated_message is not None
    assert validated_message.type == "subscribe"

    # Verify ack indicates success
    assert ack.success is True
    assert ack.error is None

    # Verify txid matches
    message_data = json.loads(message_json)
    assert ack.txid == message_data["txid"]


@given(message_json=valid_unsubscribe_message_json_strategy())
@property_test_settings()
async def test_property_10_unsubscribe_message_acknowledgment(
    message_json: str,
) -> None:
    """
    Property 10: Unsubscribe Message Acknowledgment.

    For any valid unsubscribe message, the system should send an ack
    with success=true and the correct txid.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was validated successfully

    assert validated_message is not None
    assert validated_message.type == "unsubscribe"

    # Verify ack indicates success
    assert ack.success is True
    assert ack.error is None

    # Verify txid matches
    message_data = json.loads(message_json)
    assert ack.txid == message_data["txid"]


@given(invalid_json=invalid_json_string_strategy())
@property_test_settings()
async def test_property_10_invalid_json_acknowledgment_failure(
    invalid_json: str,
) -> None:
    """
    Property 10: Invalid JSON Acknowledgment Failure.

    For any invalid JSON, the system should send an ack with
    success=false and an error message.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Route the invalid message
    routed = await router.route_message(invalid_json)
    validated_message, ack = routed.validated_message, routed.ack

    # Verify message was not validated

    assert validated_message is None

    # Verify ack indicates failure
    assert ack.type == "ack"
    assert ack.success is False
    assert ack.error is not None
    assert len(ack.error) > 0


@given(
    txid=st.integers(min_value=0, max_value=1000000),
    invalid_type=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=1,
        max_size=20,
    ).filter(
        lambda x: x not in ["identify", "ping", "subscribe", "unsubscribe", "action"]
    ),
)
@property_test_settings()
async def test_property_10_unknown_message_type_acknowledgment_failure(
    txid: int, invalid_type: str
) -> None:
    """
    Property 10: Unknown Message Type Acknowledgment Failure.

    For any message with an unknown type, the system should send an ack
    with success=false and an error message.

    Validates: Requirements 6.5
    """
    router = MessageRouter()

    # Create message with unknown type
    message_json = json.dumps({"type": invalid_type, "txid": txid})

    # Route the message
    routed = await router.route_message(message_json)
    validated_message, ack = routed.validated_message, routed.ack


    # Verify message was not validated
    assert validated_message is None

    # Verify ack indicates failure
    assert ack.success is False
    assert ack.error is not None
    assert "Unknown message type" in ack.error or "unknown" in ack.error.lower()

    # Verify txid is preserved
    assert ack.txid == txid
