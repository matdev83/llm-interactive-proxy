"""Property-based tests for Codebuff message schema validation.

Feature: codebuff-backend-compatibility
Property 9: Schema validation
Validates: Requirements 6.3
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from src.codebuff.schemas import (
    AckMessage,
    ActionMessage,
    IdentifyMessage,
    InitAction,
    InitResponseAction,
    PingMessage,
    PromptAction,
    PromptErrorAction,
    PromptResponseAction,
    ResponseChunkAction,
    ServerActionMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating valid message data
# ============================================================================


@st.composite
def valid_identify_message_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid identify message data."""
    return {
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


@st.composite
def valid_ping_message_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid ping message data."""
    return {
        "type": "ping",
        "txid": draw(st.integers(min_value=0, max_value=1000000)),
    }


@st.composite
def valid_subscribe_message_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid subscribe message data."""
    return {
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


@st.composite
def valid_unsubscribe_message_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid unsubscribe message data."""
    return {
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


@st.composite
def valid_prompt_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid prompt action data."""
    return {
        "type": "prompt",
        "promptId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "prompt": draw(st.one_of(st.none(), st.text(min_size=1, max_size=500))),
        "content": draw(
            st.one_of(
                st.none(),
                st.lists(
                    st.fixed_dictionaries(
                        {
                            "role": st.sampled_from(["user", "assistant", "system"]),
                            "content": st.text(min_size=1, max_size=100),
                        }
                    ),
                    max_size=5,
                ),
            )
        ),
        "promptParams": draw(
            st.one_of(st.none(), st.dictionaries(st.text(), st.text(), max_size=5))
        ),
        "fingerprintId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "authToken": draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
        "costMode": draw(st.sampled_from(["normal", "fast", "premium"])),
        "sessionState": draw(
            st.dictionaries(st.text(), st.text(), min_size=1, max_size=10)
        ),
        "toolResults": draw(
            st.lists(st.dictionaries(st.text(), st.text()), max_size=5)
        ),
        "model": draw(
            st.one_of(
                st.none(),
                st.sampled_from(
                    [
                        "gpt-4",
                        "gpt-3.5-turbo",
                        "claude-3-opus",
                        "claude-3-sonnet",
                        "gemini-pro",
                    ]
                ),
            )
        ),
        "repoUrl": draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
        "agentId": draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
    }


@st.composite
def valid_init_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid init action data."""
    return {
        "type": "init",
        "fingerprintId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "authToken": draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
        "fileContext": draw(
            st.dictionaries(st.text(), st.text(), min_size=1, max_size=10)
        ),
        "repoUrl": draw(st.one_of(st.none(), st.text(min_size=10, max_size=100))),
    }


@st.composite
def valid_ack_message_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid ack message data."""
    success = draw(st.booleans())
    return {
        "type": "ack",
        "txid": draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1000000))),
        "success": success,
        "error": (
            draw(st.one_of(st.none(), st.text(min_size=1, max_size=200)))
            if not success
            else None
        ),
    }


@st.composite
def valid_response_chunk_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid response chunk action data."""
    return {
        "type": "response-chunk",
        "userInputId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "chunk": draw(st.text(min_size=1, max_size=500)),
    }


@st.composite
def valid_prompt_response_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid prompt response action data."""
    return {
        "type": "prompt-response",
        "promptId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "sessionState": draw(
            st.dictionaries(st.text(), st.text(), min_size=0, max_size=10)
        ),
        "toolCalls": draw(
            st.one_of(
                st.none(),
                st.lists(
                    st.fixed_dictionaries(
                        {
                            "id": st.text(
                                alphabet=st.characters(
                                    whitelist_categories=("Lu", "Ll", "Nd"),
                                    whitelist_characters="-_",
                                ),
                                min_size=1,
                                max_size=50,
                            ),
                            "type": st.just("function"),
                            "function": st.fixed_dictionaries(
                                {
                                    "name": st.text(
                                        alphabet=st.characters(
                                            whitelist_categories=("Lu", "Ll", "Nd"),
                                            whitelist_characters="-_",
                                        ),
                                        min_size=1,
                                        max_size=50,
                                    ),
                                    "arguments": st.text(min_size=1, max_size=100),
                                }
                            ),
                        }
                    ),
                    max_size=5,
                ),
            )
        ),
        "toolResults": draw(
            st.one_of(
                st.none(), st.lists(st.dictionaries(st.text(), st.text()), max_size=5)
            )
        ),
        "output": draw(
            st.one_of(st.none(), st.dictionaries(st.text(), st.text(), max_size=5))
        ),
    }


@st.composite
def valid_prompt_error_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid prompt error action data."""
    return {
        "type": "prompt-error",
        "userInputId": draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
                ),
                min_size=1,
                max_size=50,
            )
        ),
        "message": draw(st.text(min_size=1, max_size=200)),
        "error": draw(st.one_of(st.none(), st.text(min_size=1, max_size=500))),
        "remainingBalance": draw(
            st.one_of(st.none(), st.floats(min_value=0.0, max_value=1000000.0))
        ),
    }


@st.composite
def valid_init_response_action_strategy(draw: Any) -> dict[str, Any]:
    """Generate valid init response action data."""
    return {
        "type": "init-response",
        "message": draw(st.one_of(st.none(), st.text(min_size=1, max_size=200))),
        "agentNames": draw(
            st.one_of(st.none(), st.dictionaries(st.text(), st.text(), max_size=5))
        ),
        "usage": draw(st.floats(min_value=0.0, max_value=1000.0)),
        "remainingBalance": draw(st.floats(min_value=0.0, max_value=1000000.0)),
        "next_quota_reset": draw(st.one_of(st.none(), st.datetimes())),
    }


# ============================================================================
# Property Tests for Client Messages
# ============================================================================


@given(message_data=valid_identify_message_strategy())
@property_test_settings()
def test_property_9_identify_message_validation(message_data: dict[str, Any]) -> None:
    """
    Property 9: Identify Message Validation.

    For any valid identify message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    message = IdentifyMessage(**message_data)

    # Verify required fields are present
    assert message.type == "identify"
    assert message.txid == message_data["txid"]
    assert message.clientSessionId == message_data["clientSessionId"]


@given(message_data=valid_ping_message_strategy())
@property_test_settings()
def test_property_9_ping_message_validation(message_data: dict[str, Any]) -> None:
    """
    Property 9: Ping Message Validation.

    For any valid ping message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    message = PingMessage(**message_data)

    # Verify required fields are present
    assert message.type == "ping"
    assert message.txid == message_data["txid"]


@given(message_data=valid_subscribe_message_strategy())
@property_test_settings()
def test_property_9_subscribe_message_validation(message_data: dict[str, Any]) -> None:
    """
    Property 9: Subscribe Message Validation.

    For any valid subscribe message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    message = SubscribeMessage(**message_data)

    # Verify required fields are present
    assert message.type == "subscribe"
    assert message.txid == message_data["txid"]
    assert message.topics == message_data["topics"]


@given(message_data=valid_unsubscribe_message_strategy())
@property_test_settings()
def test_property_9_unsubscribe_message_validation(
    message_data: dict[str, Any]
) -> None:
    """
    Property 9: Unsubscribe Message Validation.

    For any valid unsubscribe message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    message = UnsubscribeMessage(**message_data)

    # Verify required fields are present
    assert message.type == "unsubscribe"
    assert message.txid == message_data["txid"]
    assert message.topics == message_data["topics"]


@given(action_data=valid_prompt_action_strategy())
@property_test_settings()
def test_property_9_prompt_action_validation(action_data: dict[str, Any]) -> None:
    """
    Property 9: Prompt Action Validation.

    For any valid prompt action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = PromptAction(**action_data)

    # Verify required fields are present
    assert action.type == "prompt"
    assert action.promptId == action_data["promptId"]
    assert action.fingerprintId == action_data["fingerprintId"]
    assert action.sessionState == action_data["sessionState"]


@given(action_data=valid_init_action_strategy())
@property_test_settings()
def test_property_9_init_action_validation(action_data: dict[str, Any]) -> None:
    """
    Property 9: Init Action Validation.

    For any valid init action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = InitAction(**action_data)

    # Verify required fields are present
    assert action.type == "init"
    assert action.fingerprintId == action_data["fingerprintId"]
    assert action.fileContext == action_data["fileContext"]


@given(
    txid=st.integers(min_value=0, max_value=1000000),
    action_data=st.one_of(valid_prompt_action_strategy(), valid_init_action_strategy()),
)
@property_test_settings()
def test_property_9_action_message_validation(
    txid: int, action_data: dict[str, Any]
) -> None:
    """
    Property 9: Action Message Validation.

    For any valid action message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Create action message wrapper
    message_data = {"type": "action", "txid": txid, "data": action_data}

    # Should parse successfully
    message = ActionMessage(**message_data)

    # Verify required fields are present
    assert message.type == "action"
    assert message.txid == txid
    assert message.data.type == action_data["type"]


# ============================================================================
# Property Tests for Server Messages
# ============================================================================


@given(message_data=valid_ack_message_strategy())
@property_test_settings()
def test_property_9_ack_message_validation(message_data: dict[str, Any]) -> None:
    """
    Property 9: Ack Message Validation.

    For any valid ack message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    message = AckMessage(**message_data)

    # Verify required fields are present
    assert message.type == "ack"
    assert message.success == message_data["success"]


@given(action_data=valid_response_chunk_action_strategy())
@property_test_settings()
def test_property_9_response_chunk_action_validation(
    action_data: dict[str, Any]
) -> None:
    """
    Property 9: Response Chunk Action Validation.

    For any valid response chunk action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = ResponseChunkAction(**action_data)

    # Verify required fields are present
    assert action.type == "response-chunk"
    assert action.userInputId == action_data["userInputId"]
    assert action.chunk == action_data["chunk"]


@given(action_data=valid_prompt_response_action_strategy())
@property_test_settings()
def test_property_9_prompt_response_action_validation(
    action_data: dict[str, Any]
) -> None:
    """
    Property 9: Prompt Response Action Validation.

    For any valid prompt response action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = PromptResponseAction(**action_data)

    # Verify required fields are present
    assert action.type == "prompt-response"
    assert action.promptId == action_data["promptId"]
    assert action.sessionState == action_data["sessionState"]


@given(action_data=valid_prompt_error_action_strategy())
@property_test_settings()
def test_property_9_prompt_error_action_validation(action_data: dict[str, Any]) -> None:
    """
    Property 9: Prompt Error Action Validation.

    For any valid prompt error action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = PromptErrorAction(**action_data)

    # Verify required fields are present
    assert action.type == "prompt-error"
    assert action.userInputId == action_data["userInputId"]
    assert action.message == action_data["message"]


@given(action_data=valid_init_response_action_strategy())
@property_test_settings()
def test_property_9_init_response_action_validation(
    action_data: dict[str, Any]
) -> None:
    """
    Property 9: Init Response Action Validation.

    For any valid init response action data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Should parse successfully
    action = InitResponseAction(**action_data)

    # Verify required fields are present
    assert action.type == "init-response"
    assert action.usage == action_data["usage"]
    assert action.remainingBalance == action_data["remainingBalance"]


@given(
    action_data=st.one_of(
        valid_response_chunk_action_strategy(),
        valid_prompt_response_action_strategy(),
        valid_prompt_error_action_strategy(),
        valid_init_response_action_strategy(),
    )
)
@property_test_settings()
def test_property_9_server_action_message_validation(
    action_data: dict[str, Any]
) -> None:
    """
    Property 9: Server Action Message Validation.

    For any valid server action message data, the schema should successfully
    parse and validate it without raising exceptions.

    Validates: Requirements 6.3
    """
    # Create server action message wrapper
    message_data = {"type": "action", "data": action_data}

    # Should parse successfully
    message = ServerActionMessage(**message_data)

    # Verify required fields are present
    assert message.type == "action"
    assert message.data.type == action_data["type"]


# ============================================================================
# Property Tests for Invalid Messages
# ============================================================================


@given(
    invalid_type=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
        min_size=1,
        max_size=20,
    ).filter(
        lambda x: x not in ["identify", "ping", "subscribe", "unsubscribe", "action"]
    )
)
@property_test_settings()
def test_property_9_invalid_message_type_rejection(invalid_type: str) -> None:
    """
    Property 9: Invalid Message Type Rejection.

    For any message with an invalid type, the schema should reject it
    with a validation error.

    Validates: Requirements 6.3
    """
    # Create message with invalid type
    message_data = {
        "type": invalid_type,
        "txid": 123,
    }

    # Should raise ValidationError
    try:
        IdentifyMessage(**message_data)
        raise AssertionError(f"Should have rejected invalid type '{invalid_type}'")
    except ValidationError:
        pass  # Expected


@given(message_data=valid_identify_message_strategy())
@property_test_settings()
def test_property_9_missing_required_field_rejection(
    message_data: dict[str, Any]
) -> None:
    """
    Property 9: Missing Required Field Rejection.

    For any message missing a required field, the schema should reject it
    with a validation error.

    Validates: Requirements 6.3
    """
    # Remove a required field
    incomplete_data = message_data.copy()
    del incomplete_data["clientSessionId"]

    # Should raise ValidationError
    try:
        IdentifyMessage(**incomplete_data)
        raise AssertionError("Should have rejected message missing required field")
    except ValidationError:
        pass  # Expected


@given(
    message_data=valid_prompt_action_strategy(),
    invalid_txid=st.one_of(
        st.lists(st.integers()),
        st.dictionaries(st.text(), st.text()),
    ),
)
@property_test_settings()
def test_property_9_invalid_field_type_rejection(
    message_data: dict[str, Any], invalid_txid: Any
) -> None:
    """
    Property 9: Invalid Field Type Rejection.

    For any message with a field of the wrong type, the schema should
    reject it with a validation error.

    Validates: Requirements 6.3
    """
    # Create action message with invalid txid type (list or dict instead of int)
    invalid_message_data = {
        "type": "action",
        "txid": invalid_txid,
        "data": message_data,
    }

    # Should raise ValidationError
    try:
        ActionMessage(**invalid_message_data)
        raise AssertionError(
            f"Should have rejected invalid txid type: {type(invalid_txid)}"
        )
    except (ValidationError, TypeError):
        pass  # Expected
