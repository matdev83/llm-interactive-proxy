"""
Integration tests for Tool Call Reactor system.
"""

from __future__ import annotations

import json

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.di.services import get_service_provider
from src.core.domain.responses import ProcessedResponse
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware
from src.core.services.tool_call_reactor_service import ToolCallReactorService


class TestToolCallReactorIntegration:
    """Integration tests for the complete tool call reactor system."""

    @pytest.fixture
    def service_provider(self):
        """Get the service provider for integration tests."""
        return get_service_provider()

    @pytest.fixture
    def reactor_service(self, service_provider):
        """Get the tool call reactor service."""
        return service_provider.get_required_service(ToolCallReactorService)

    @pytest.fixture
    def reactor_middleware(self, service_provider):
        """Get the tool call reactor middleware."""
        return service_provider.get_required_service(ToolCallReactorMiddleware)

    @pytest.mark.asyncio
    async def test_apply_diff_steering_integration(
        self, reactor_service, reactor_middleware
    ):
        """Test end-to-end apply_diff steering functionality."""
        # Ensure a config-based steering handler is present (DI normally provides it)
        handlers = reactor_service.get_registered_handlers()
        if "config_steering_handler" not in handlers:
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )

            config_handler = ConfigSteeringHandler(
                rules=[
                    {
                        "name": "apply_diff_to_patch_file",
                        "enabled": True,
                        "priority": 100,
                        "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                        "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                        "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                    }
                ]
            )
            await reactor_service.register_handler(config_handler)

        # Create a response with apply_diff tool call
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "apply_diff",
                                    "arguments": json.dumps(
                                        {
                                            "file_path": "test.py",
                                            "diff": "@@ -1,3 +1,5 @@\n-old code\n+new code",
                                        }
                                    ),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(
            content=json.dumps(tool_call_response),
            usage={"prompt_tokens": 10, "completion_tokens": 20},
            metadata={"original": "metadata"},
        )

        # Process through middleware
        result = await reactor_middleware.process(
            response=response,
            session_id="integration_test_session",
            context={
                "backend_name": "test_backend",
                "model_name": "test_model",
                "calling_agent": "test_agent",
            },
        )

        # Verify the tool call was swallowed and steering was provided
        assert isinstance(result, ProcessedResponse)
        assert result != response  # Should be a new response object

        # Check that steering message was provided
        assert "patch_file" in result.content.lower()
        assert "apply_diff" in result.content.lower()
        assert "superior" in result.content.lower()

        # Check metadata
        assert result.metadata["tool_call_swallowed"] is True
        assert "original_tool_call" in result.metadata
        assert result.metadata["original"] == "metadata"  # Original metadata preserved

        # Check usage is preserved
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 20}

    @pytest.mark.asyncio
    async def test_rate_limiting_integration(self, reactor_service, reactor_middleware):
        """Test rate limiting functionality in integration."""
        # Ensure a config-based steering handler is present
        handlers = reactor_service.get_registered_handlers()
        if "config_steering_handler" not in handlers:
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )

            config_handler = ConfigSteeringHandler(
                rules=[
                    {
                        "name": "apply_diff_to_patch_file",
                        "enabled": True,
                        "priority": 100,
                        "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                        "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                        "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                    }
                ]
            )
            await reactor_service.register_handler(config_handler)
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "apply_diff",
                                    "arguments": json.dumps(
                                        {
                                            "file_path": "test.py",
                                            "diff": "@@ -1,3 +1,5 @@\n-old code\n+new code",
                                        }
                                    ),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        # First call should provide steering
        result1 = await reactor_middleware.process(
            response=response,
            session_id="rate_limit_test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert isinstance(result1, ProcessedResponse)
        assert "patch_file" in result1.content.lower()

        # Second call within rate limit window should not provide steering
        result2 = await reactor_middleware.process(
            response=response,
            session_id="rate_limit_test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should return original response (tool call not swallowed)
        assert result2 == response

    @pytest.mark.asyncio
    async def test_non_apply_diff_tool_passthrough(self, reactor_middleware):
        """Test that non-apply_diff tool calls pass through unchanged."""
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_456",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({"file_path": "test.py"}),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        # Process through middleware
        result = await reactor_middleware.process(
            response=response,
            session_id="passthrough_test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should return original response unchanged
        assert result == response

    @pytest.mark.asyncio
    async def test_multiple_tool_calls_mixed(self, reactor_service, reactor_middleware):
        """Test processing multiple tool calls with mixed handling."""
        # Ensure a config-based steering handler is present
        handlers = reactor_service.get_registered_handlers()
        if "config_steering_handler" not in handlers:
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )

            config_handler = ConfigSteeringHandler(
                rules=[
                    {
                        "name": "apply_diff_to_patch_file",
                        "enabled": True,
                        "priority": 100,
                        "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                        "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                        "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                    }
                ]
            )
            await reactor_service.register_handler(config_handler)
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "apply_diff",
                                    "arguments": json.dumps(
                                        {
                                            "file_path": "test.py",
                                            "diff": "@@ -1,3 +1,5 @@\n-old code\n+new code",
                                        }
                                    ),
                                },
                            },
                            {
                                "id": "call_456",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({"file_path": "other.py"}),
                                },
                            },
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        # Process through middleware
        result = await reactor_middleware.process(
            response=response,
            session_id="mixed_tools_test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should swallow the apply_diff call and provide steering
        assert isinstance(result, ProcessedResponse)
        assert result != response
        assert "patch_file" in result.content.lower()
        assert result.metadata["tool_call_swallowed"] is True

    @pytest.mark.asyncio
    async def test_different_sessions_independent_rate_limiting(
        self, reactor_service, reactor_middleware
    ):
        """Test that rate limiting works independently per session."""
        # Ensure a config-based steering handler is present
        handlers = reactor_service.get_registered_handlers()
        if "config_steering_handler" not in handlers:
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )

            config_handler = ConfigSteeringHandler(
                rules=[
                    {
                        "name": "apply_diff_to_patch_file",
                        "enabled": True,
                        "priority": 100,
                        "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                        "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                        "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                    }
                ]
            )
            await reactor_service.register_handler(config_handler)
        tool_call_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "apply_diff",
                                    "arguments": json.dumps(
                                        {
                                            "file_path": "test.py",
                                            "diff": "@@ -1,3 +1,5 @@\n-old code\n+new code",
                                        }
                                    ),
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(tool_call_response))

        # First call for session1 should provide steering
        result1 = await reactor_middleware.process(
            response=response,
            session_id="session1",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert isinstance(result1, ProcessedResponse)
        assert "patch_file" in result1.content.lower()

        # First call for session2 should also provide steering (different session)
        result2 = await reactor_middleware.process(
            response=response,
            session_id="session2",
            context={"backend_name": "test", "model_name": "test"},
        )

        assert isinstance(result2, ProcessedResponse)
        assert "patch_file" in result2.content.lower()

    @pytest.mark.asyncio
    async def test_malformed_tool_call_handling(self, reactor_middleware):
        """Test handling of malformed tool calls."""
        # Response with malformed tool call (missing function name)
        malformed_response = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "arguments": json.dumps({"arg": "value"})
                                    # Missing "name" field
                                },
                            }
                        ]
                    }
                }
            ]
        }

        response = ProcessedResponse(content=json.dumps(malformed_response))

        # Should handle gracefully without crashing
        result = await reactor_middleware.process(
            response=response,
            session_id="malformed_test_session",
            context={"backend_name": "test", "model_name": "test"},
        )

        # Should return original response
        assert result == response

    def test_middleware_configuration(self, reactor_service, reactor_middleware):
        """Test middleware configuration and handler management."""
        # Ensure a config-based steering handler is present
        handlers = reactor_service.get_registered_handlers()
        if "config_steering_handler" not in handlers:
            from src.core.services.tool_call_handlers.config_steering_handler import (
                ConfigSteeringHandler,
            )

            config_handler = ConfigSteeringHandler(
                rules=[
                    {
                        "name": "apply_diff_to_patch_file",
                        "enabled": True,
                        "priority": 100,
                        "triggers": {"tool_names": ["apply_diff"], "phrases": []},
                        "message": "You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.",
                        "rate_limit": {"calls_per_window": 1, "window_seconds": 60},
                    }
                ]
            )
            # Register handler synchronously for this test
            import asyncio

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    reactor_service.register_handler(config_handler)
                )
            finally:
                loop.close()

        # Check that handlers are registered
        handlers = reactor_middleware.get_registered_handlers()
        assert len(handlers) > 0
        assert "config_steering_handler" in handlers

        # Test enabling/disabling
        reactor_middleware.set_enabled(False)
        assert reactor_middleware._enabled is False

        reactor_middleware.set_enabled(True)
        assert reactor_middleware._enabled is True
