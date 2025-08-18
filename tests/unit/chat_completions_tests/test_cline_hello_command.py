from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import get_backend_instance, get_session_service_from_app


@pytest.mark.asyncio
async def test_cline_hello_command_tool_calls(
    interactive_client, mock_openrouter_backend
):
    """Test that !/hello command returns tool calls for Cline agent."""

    # First, simulate a Cline agent by sending a message with <attempt_completion>
    # This should trigger Cline agent detection
    backend = get_backend_instance(interactive_client.app, "openrouter")
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = {
            "choices": [{"message": {"content": "I understand"}}]
        }

        # Send a message that contains <attempt_completion> to trigger Cline detection
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>",
                }
            ],
        }
        # Add authorization header to avoid 401 error
        headers = {"Authorization": "Bearer test-proxy-key"}
        resp = interactive_client.post(
            "/v1/chat/completions", json=payload, headers=headers
        )

        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    print("Hello command response:")
    print(content)

    # Should contain XML-wrapped response for Cline agent
    assert "<attempt_completion>" in content
    assert "</attempt_completion>" in content
    assert "Hello! I am the interactive proxy." in content


@pytest.mark.asyncio
async def test_cline_hello_command_same_request(interactive_client):
    """Test !/hello command when Cline detection and command are in the same request."""

    backend = get_backend_instance(interactive_client.app, "openrouter")
    # Send a message that contains BOTH <attempt_completion> AND !/hello in the same request
    # This simulates what might happen in real Cline usage
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # The !/hello command should be handled locally, so the backend should not be called
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "I am using Cline. <attempt_completion>test</attempt_completion> !/hello",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        # Backend should NOT be called for local commands
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    # Get the session to check if Cline agent was detected
    session_service = get_session_service_from_app(interactive_client.app)
    session = await session_service.get_session("default")
    print(
        f"DEBUG: is_cline_agent after same-request detection = {session.state.is_cline_agent}"
    )
    print(f"DEBUG: session.agent = {session.agent}")

    # The response should be a tool call since Cline was detected in the same request
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
    assert (
        data["choices"][0].get("finish_reason") == "tool_calls"
    ), "Finish reason should be tool_calls"


@pytest.mark.asyncio
async def test_cline_hello_with_attempt_completion_only(interactive_client):
    """Test !/hello when only <attempt_completion> is present (real-world Cline scenario)."""

    backend = get_backend_instance(interactive_client.app, "openrouter")
    # This simulates the EXACT real-world scenario: Cline sends a message with <attempt_completion>
    # and !/hello, but without the keyword "cline" in the text
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        # The !/hello command should be handled locally, so the backend should not be called
        payload = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "<attempt_completion>test</attempt_completion> !/hello",
                }
            ],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        # Backend should NOT be called for local commands
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    # Get the session to check if Cline agent was detected
    session_service = get_session_service_from_app(interactive_client.app)
    session = await session_service.get_session("default")
    print(
        f"DEBUG: is_cline_agent after attempt_completion-only detection = {session.state.is_cline_agent}"
    )
    print(f"DEBUG: session.agent = {session.agent}")

    # The response should be a tool call since <attempt_completion> was detected
    message = data["choices"][0]["message"]
    assert message.get("content") is None, "Content should be None for tool calls"
    assert message.get("tool_calls") is not None, "Tool calls should be present"
    assert len(message["tool_calls"]) == 1, "Should have exactly one tool call"
    assert (
        data["choices"][0].get("finish_reason") == "tool_calls"
    ), "Finish reason should be tool_calls"


@pytest.mark.asyncio
async def test_cline_hello_command_first_message(interactive_client):
    """Test !/hello as the very first message without prior Cline detection."""

    backend = get_backend_instance(interactive_client.app, "openrouter")
    # Send !/hello as the very first message without any prior Cline detection
    # This simulates the real-world scenario you encountered
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "!/hello"}],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        # Backend should NOT be called for local commands
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    # Get the session to check agent detection status
    session_service = get_session_service_from_app(interactive_client.app)
    session = await session_service.get_session("default")
    print(f"DEBUG: is_cline_agent for first message = {session.state.is_cline_agent}")
    print(f"DEBUG: session.agent = {session.agent}")

    content = data["choices"][0]["message"]["content"]
    print(f"First message hello command response content: {content!r}")

    # Without prior Cline detection, this should NOT be wrapped in XML
    assert not content.startswith(
        "<attempt_completion>"
    ), f"Response should NOT be wrapped in XML without Cline detection, got: {content[:100]}"
    assert "Hello, this is" in content
    assert "hello acknowledged" in content


@pytest.mark.asyncio
async def test_non_cline_hello_command_no_xml_wrapping(interactive_client):
    """Test that !/hello command is NOT wrapped in XML for non-Cline agents."""

    backend = get_backend_instance(interactive_client.app, "openrouter")
    # Send !/hello command without triggering Cline agent detection
    with patch.object(
        backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "!/hello"}],
        }
        resp = interactive_client.post("/v1/chat/completions", json=payload)

        # Backend should NOT be called for local commands
        mock_method.assert_not_called()

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"

    content = data["choices"][0]["message"]["content"]
    print(f"Non-Cline hello command response content: {content!r}")

    # For non-Cline agent, the response should NOT be wrapped in XML
    assert not content.startswith(
        "<attempt_completion>"
    ), f"Response should NOT be wrapped in XML for non-Cline, got: {content[:100]}"
    assert "Hello, this is" in content
    assert "hello acknowledged" in content
