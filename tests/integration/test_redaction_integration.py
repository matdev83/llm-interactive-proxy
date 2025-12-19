"""
Integration test for redaction functionality.
"""

from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AuthConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.security import APIKeyRedactor, ProxyCommandFilter


def test_redaction_functionality():
    """Test that redaction works correctly."""
    # Create redactor and filter
    redactor = APIKeyRedactor(["SECRET_ABC123", "API_KEY_XYZ"])
    filter = ProxyCommandFilter("!/")

    # Test content with secrets and commands
    original_content = "Use SECRET_ABC123 to access API and run !/hello command"

    # Apply redaction and filtering
    redacted_content = redactor.redact(original_content)
    filtered_content = filter.filter_commands(redacted_content)

    # Verify redaction
    assert "SECRET_ABC123" not in filtered_content
    assert "API_KEY_XYZ" not in filtered_content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in filtered_content
    assert "!/hello" not in filtered_content


@pytest.mark.asyncio
async def test_redaction_in_request_pipeline():
    """Test redaction in a simplified request pipeline."""
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    # Create config with API keys
    auth_config = AuthConfig(
        redact_api_keys_in_prompts=True, api_keys=["SECRET_ABC123"]
    )

    app_config = MagicMock()
    app_config.auth = auth_config
    app_config.get_command_prefix.return_value = "!/"
    app_config.get_disable_commands.return_value = False

    app_state = MagicMock()
    app_state.get_setting.return_value = app_config
    app_state.get_command_prefix.return_value = "!/"
    app_state.get_disable_commands.return_value = False

    # Create transform pipeline
    pipeline = RequestTransformPipeline(app_state=app_state)

    # Create request with secret
    original_request = ChatRequest(
        model="test-model",
        messages=[
            ChatMessage(
                role="user",
                content="Use SECRET_ABC123 to access service and run !/test",
            )
        ],
    )

    # Apply transformation
    from src.core.domain.request_context import RequestContext

    context = RequestContext(
        headers={}, cookies={}, state={}, app_state={}, original_request=None
    )

    transformed_request = await pipeline.transform(
        context, None, "test-session", original_request
    )

    # Verify redaction occurred
    user_message = next(
        (m for m in transformed_request.messages if m.role == "user"), None
    )

    assert user_message is not None
    # The secret should be redacted but command filtering only applies to full request processing
    assert "SECRET_ABC123" not in user_message.content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in user_message.content


@pytest.mark.asyncio
async def test_redaction_with_streaming():
    """Test redaction works with streaming requests."""
    from src.core.services.request_transform_pipeline import RequestTransformPipeline

    # Create config with API keys
    auth_config = AuthConfig(
        redact_api_keys_in_prompts=True, api_keys=["STREAM_SECRET"]
    )

    app_config = MagicMock()
    app_config.auth = auth_config
    app_config.get_command_prefix.return_value = "!/"
    app_config.get_disable_commands.return_value = False

    app_state = MagicMock()
    app_state.get_setting.return_value = app_config
    app_state.get_command_prefix.return_value = "!/"
    app_state.get_disable_commands.return_value = False

    # Create transform pipeline
    pipeline = RequestTransformPipeline(app_state=app_state)

    # Create streaming request with secret
    original_request = ChatRequest(
        model="test-model",
        messages=[
            ChatMessage(role="user", content="Stream with STREAM_SECRET and command")
        ],
        stream=True,
    )

    # Apply transformation
    from src.core.domain.request_context import RequestContext

    context = RequestContext(
        headers={}, cookies={}, state={}, app_state={}, original_request=None
    )

    transformed_request = await pipeline.transform(
        context, None, "test-session", original_request
    )

    # Verify redaction occurred
    user_message = next(
        (m for m in transformed_request.messages if m.role == "user"), None
    )

    assert user_message is not None
    # The secret should be redacted
    assert "STREAM_SECRET" not in user_message.content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in user_message.content
    # Streaming flag should be preserved
    assert transformed_request.stream is True
