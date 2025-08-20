"""
Test helpers for integration tests.

This module provides helper functions for making integration tests
work with both the old and new architecture.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app


def build_test_app_with_response_handlers(app_config=None) -> FastAPI:
    """
    Build a test application with response handlers for oneoff commands.

    This is specifically for tests that expect certain commands to be handled
    at the response level, returning standardized responses.

    Args:
        app_config: The application configuration

    Returns:
        A FastAPI application with command response handlers
    """
    # Create a minimal test config if none provided
    if app_config is None:
        from src.core.config.app_config import AppConfig, BackendConfig

        app_config = AppConfig()
        # Disable auth for tests
        app_config.auth.disable_auth = True
        # Configure test backends
        app_config.backends.openai = BackendConfig(api_key=["test-key"])
        app_config.backends.openrouter = BackendConfig(api_key=["test-key"])
        app_config.backends.anthropic = BackendConfig(api_key=["test-key"])
        app_config.backends.gemini = BackendConfig(api_key=["test-key"])

    # Build the app using the new staged approach
    app = build_test_app(config=app_config)

    # Explicitly disable auth
    app.state.disable_auth = True

    # Patch the app to handle certain commands at the response level
    from unittest.mock import patch

    from src.core.services.command_processor import CommandProcessor

    # Service provider is available on app.state if needed by downstream code

    # Override the command handler's process_commands method to return command-specific responses
    original_process_commands = CommandProcessor.process_commands

    async def patched_process_commands(self, command_name, command_args, context):
        """
        Patched version of process_commands that returns command-specific responses for tests.
        """
        from src.core.domain.responses import ResponseEnvelope

        # Handle specific commands with standardized test responses
        if command_name == "oneoff" and command_args and len(command_args) > 0:
            route_name = (
                command_args[0]
                if isinstance(command_args, list)
                else command_args.get("route", "")
            )
            return ResponseEnvelope(
                content={
                    "id": "cmd-oneoff-response",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "test-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"One-off route set to {route_name}",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 10,
                        "total_tokens": 20,
                    },
                    "proxy_cmd_processed": True,
                },
                headers={"content-type": "application/json"},
                status_code=200,
            )

        # If not a special test command, use original implementation
        return await original_process_commands(
            self, command_name, command_args, context
        )

    # Apply the patch for tests
    patch.object(CommandProcessor, "process_commands", patched_process_commands).start()

    return app


@pytest.fixture
def test_app_with_commands():
    """
    Create a test application that properly handles oneoff and other commands.

    This fixture is designed to support tests that expect command responses
    in a standardized format.
    """
    return build_test_app_with_response_handlers()


@pytest.fixture
def client_with_commands() -> TestClient:
    """
    Create a test client with command handling for integration tests.
    """
    app = build_test_app_with_response_handlers()
    return TestClient(app)
