"""
Unit tests for Tool Call Reactor Middleware.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallReactionResult,
)
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


class MockReactor:
    """Mock reactor for testing."""

    def __init__(self):
        self.process_tool_call = AsyncMock()
        self.get_registered_handlers = MagicMock(return_value=["handler1", "handler2"])

    async def register_handler(self, handler):
        pass

    async def unregister_handler(self, handler_name):
        pass


class TestToolCallReactorMiddleware:
    """Test cases for ToolCallReactorMiddleware."""

    @pytest.fixture
    def mock_reactor(self):
        """Create a mock reactor for testing."""
        return MockReactor()

    @pytest.fixture
    def middleware(self, mock_reactor):
        """Create middleware for testing."""
        return ToolCallReactorMiddleware(mock_reactor, enabled=True, priority=45)

    def test_middleware_properties(self, middleware):
        """Test middleware properties."""
        assert middleware.priority == 45

    @pytest.mark.asyncio
    async def test_process_no_content(self, middleware):
        """Test processing response with no content."""
        response = ProcessedResponse(content="")

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response

    @pytest.mark.asyncio
    async def test_process_disabled_middleware(self, mock_reactor):
        """Test processing when middleware is disabled."""
        middleware = ToolCallReactorMiddleware(mock_reactor, enabled=False)

        response = ProcessedResponse(content='{"test": "content"}')

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_no_tool_calls(self, middleware, mock_reactor):
        """Test processing response with no tool calls."""
        response = ProcessedResponse(
            content='{"choices": [{"message": {"content": "hello"}}]}'
        )

        mock_reactor.process_tool_call.return_value = None

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_with_tool_calls_no_swallow(self, middleware, mock_reactor):
        """Test processing response with tool calls that are not swallowed."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        mock_reactor.process_tool_call.return_value = None

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_called_once()

        # Verify the call arguments
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.session_id == "test_session"
        assert call_args.tool_name == "test_tool"
        assert call_args.tool_arguments == {"arg": "value"}

    @pytest.mark.asyncio
    async def test_process_preserves_raw_arguments_on_parse_failure(
        self, middleware, mock_reactor, monkeypatch
    ):
        """Unparseable argument strings should reach handlers unchanged."""

        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_789",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": "pytest -q",
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        original_loads = json.loads

        def _raise_decode_error(value: str, *args, **kwargs):
            if value == "pytest -q":
                raise json.JSONDecodeError("invalid", value, 0)
            return original_loads(value, *args, **kwargs)

        monkeypatch.setattr(
            "src.core.services.tool_call_reactor_middleware.repair_json",
            lambda s: s,
        )
        monkeypatch.setattr(
            "src.core.services.tool_call_reactor_middleware.json.loads",
            _raise_decode_error,
        )

        mock_reactor.process_tool_call.return_value = None

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_arguments == "pytest -q"

    @pytest.mark.asyncio
    async def test_process_with_json_list_arguments(self, middleware, mock_reactor):
        """JSON arrays in argument payloads should be preserved."""

        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_101",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": '["pytest", "-k", "fast"]',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_arguments == ["pytest", "-k", "fast"]

    @pytest.mark.asyncio
    async def test_process_with_tool_call_list_payload(self, middleware, mock_reactor):
        """Tool calls provided as a list should be processed correctly."""
        tool_call_response = [
            {
                "id": "call_456",
                "type": "function",
                "function": {
                    "name": "list_tool",
                    "arguments": {"param": "data"},
                },
            }
        ]

        response = ProcessedResponse(content=tool_call_response)
        mock_reactor.process_tool_call.return_value = None

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_name == "list_tool"
        assert call_args.tool_arguments == {"param": "data"}

    @pytest.mark.asyncio
    async def test_process_with_tool_calls_swallowed(self, middleware, mock_reactor):
        """Test processing response with tool calls that are swallowed."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(
            content=json.dumps(tool_call_response),
            usage={"tokens": 100},
            metadata={"original": "metadata"},
        )

        swallow_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response="steering message",
            metadata={"handler": "test_handler"},
        )

        mock_reactor.process_tool_call.return_value = swallow_result

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Verify result is a new ProcessedResponse
        assert isinstance(result, ProcessedResponse)
        assert result != response  # Should be a new object
        assert result.content == "steering message"
        assert result.usage == {"tokens": 100}
        assert "tool_call_swallowed" in result.metadata
        assert "original_tool_call" in result.metadata
        assert result.metadata["original"] == "metadata"
        assert result.metadata["tool_call_reactor"]["handler"] == "test_handler"

    @pytest.mark.asyncio
    async def test_process_with_tool_calls_swallowed_merges_metadata(
        self, middleware, mock_reactor
    ):
        """Tool call metadata from handler should merge with existing entries."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(
            content=json.dumps(tool_call_response),
            metadata={
                "existing": True,
                "tool_call_reactor": {"previous": "data"},
            },
        )

        swallow_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response="steering message",
            metadata={"handler": "test_handler", "extra": "info"},
        )

        mock_reactor.process_tool_call.return_value = swallow_result

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert isinstance(result, ProcessedResponse)
        assert result.metadata["existing"] is True
        assert result.metadata["tool_call_reactor"] == {
            "previous": "data",
            "handler": "test_handler",
            "extra": "info",
        }

    @pytest.mark.asyncio
    async def test_process_with_tool_calls_swallowed_no_replacement(
        self, middleware, mock_reactor
    ):
        """Test processing response with swallowed tool calls but no replacement content."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        swallow_result = ToolCallReactionResult(
            should_swallow=True,
            replacement_response=None,
            metadata={"handler": "test_handler"},
        )

        mock_reactor.process_tool_call.return_value = swallow_result

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should return original response if no replacement provided
        assert result == response

    @pytest.mark.asyncio
    async def test_process_multiple_tool_calls(self, middleware, mock_reactor):
        """Test processing response with multiple tool calls."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "tool1",
                                    "arguments": '{"arg1": "value1"}',
                                },
                            },
                            {
                                "id": "call_456",
                                "type": "function",
                                "function": {
                                    "name": "tool2",
                                    "arguments": '{"arg2": "value2"}',
                                },
                            },
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        # First call not swallowed, second call swallowed
        mock_reactor.process_tool_call.side_effect = [
            None,  # First tool call not swallowed
            ToolCallReactionResult(  # Second tool call swallowed
                should_swallow=True,
                replacement_response="steering message",
                metadata={"handler": "test_handler"},
            ),
        ]

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should have called process_tool_call twice
        assert mock_reactor.process_tool_call.call_count == 2

        # Should return replacement response from second call
        assert isinstance(result, ProcessedResponse)
        assert result.content == "steering message"

    @pytest.mark.asyncio
    async def test_process_openai_format_tool_calls(self, middleware, mock_reactor):
        """Test processing OpenAI format tool calls."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "openai", "model_name": "gpt-4"},
        )

        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_name == "test_tool"
        assert call_args.backend_name == "openai"
        assert call_args.model_name == "gpt-4"

    @pytest.mark.asyncio
    async def test_process_direct_tool_calls_array(self, middleware, mock_reactor):
        """Test processing direct tool calls array."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"arg": "value"}'},
            }
        ]

        response = ProcessedResponse(content=json.dumps(tool_calls))
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_name == "test_tool"

    @pytest.mark.asyncio
    async def test_process_list_tool_calls_array(self, middleware, mock_reactor):
        """Test processing when response content is already a list of tool calls."""
        tool_calls = [
            {
                "id": "call_456",
                "type": "function",
                "function": {"name": "list_tool", "arguments": '{"foo": "bar"}'},
            }
        ]

        response = ProcessedResponse(content=tool_calls)
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_name == "list_tool"

    @pytest.mark.asyncio
    async def test_process_invalid_json_content(self, middleware, mock_reactor):
        """Test processing response with invalid JSON content."""
        response = ProcessedResponse(content="invalid json")

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_tool_call_with_null_function(self, middleware, mock_reactor):
        """Tool calls with null function payload should be skipped safely."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": None,
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        result = await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert result == response
        mock_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_dict_content(self, middleware, mock_reactor):
        """Test processing response with dict content."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        mock_reactor.process_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_metadata_tool_calls_domain_model(self, middleware, mock_reactor):
        """Metadata tool_calls provided as models should be normalized."""

        class DummyToolCall:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def model_dump(self) -> dict[str, Any]:
                return self._payload

        tool_call = DummyToolCall(
            {
                "id": "call_meta",
                "type": "function",
                "function": {"name": "meta_tool", "arguments": "{}"},
            }
        )

        response = ProcessedResponse(content="", metadata={"tool_calls": [tool_call]})
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.tool_name == "meta_tool"

    def test_get_registered_handlers(self, middleware, mock_reactor):
        """Test getting registered handlers."""
        handlers = middleware.get_registered_handlers()
        assert handlers == ["handler1", "handler2"]
        mock_reactor.get_registered_handlers.assert_called_once()

    @pytest.mark.asyncio
    async def test_register_handler(self, middleware, mock_reactor):
        """Test registering a handler."""
        handler = MagicMock()
        await middleware.register_handler(handler)
        # Should delegate to reactor
        # Note: Mock doesn't actually call the method, just records it was called

    @pytest.mark.asyncio
    async def test_unregister_handler(self, middleware, mock_reactor):
        """Test unregistering a handler."""
        await middleware.unregister_handler("test_handler")
        # Should delegate to reactor

    def test_set_enabled(self, middleware):
        """Test enabling/disabling middleware."""
        assert middleware._enabled is True

        middleware.set_enabled(False)
        assert middleware._enabled is False

        middleware.set_enabled(True)
        assert middleware._enabled is True

    @pytest.mark.asyncio
    async def test_process_with_calling_agent(self, middleware, mock_reactor):
        """Test processing with calling agent information."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "test_tool",
                                    "arguments": '{"arg": "value"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))
        mock_reactor.process_tool_call.return_value = None

        await middleware.process(
            response=response,
            session_id="test_session",
            context={
                "backend_name": "test",
                "model_name": "test",
                "calling_agent": "cursor",
            },
        )

        mock_reactor.process_tool_call.assert_called_once()
        call_args = mock_reactor.process_tool_call.call_args[0][0]
        assert call_args.calling_agent == "cursor"
