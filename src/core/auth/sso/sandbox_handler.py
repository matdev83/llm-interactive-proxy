"""
Sandbox handler for unauthenticated SSO requests.

This module provides the SandboxHandler class that generates restricted
responses for unauthenticated users, guiding them through the SSO
authentication process.
"""

import time
from typing import Any


class SandboxHandler:
    """Handles requests from unauthenticated users."""

    def __init__(self, auth_url: str):
        """
        Initialize sandbox handler.

        Args:
            auth_url: Base URL for SSO authentication endpoint
        """
        self.auth_url = auth_url

    def generate_login_banner(self, auth_url: str | None = None) -> dict[str, Any]:
        """
        Generate a chat completion response containing login instructions.

        The banner includes:
            - Welcome message
            - Authentication URL
            - Instructions to configure agent after auth
            - Note that session cannot continue after auth

        Args:
            auth_url: Optional override for authentication URL.
                     If not provided, uses the instance's auth_url.

        Returns:
            OpenAI-compatible chat completion response with login banner
        """
        url = auth_url or self.auth_url

        message = (
            "# Authentication Required\n\n"
            "Welcome to the LLM Proxy with SSO authentication.\n\n"
            "To use this proxy, you need to authenticate via Single Sign-On (SSO).\n\n"
            "## Steps to Authenticate:\n\n"
            f"1. Open this URL in your browser: {url}\n"
            "2. Complete the SSO authentication with your identity provider\n"
            "3. After successful authentication, you will receive an agent token\n"
            "4. Copy the agent token and configure it in your AI agent's API key field\n\n"
            "## Important Notes:\n\n"
            "- This conversation session cannot continue after authentication\n"
            "- You must configure your agent with the Bearer token you receive\n"
            "- Once configured, start a new conversation to use the proxy\n"
            "- Your token will remain valid until your SSO session expires\n\n"
            "Please authenticate to continue."
        )

        return self.format_as_completion_response(message)

    def format_as_completion_response(self, message: str) -> dict[str, Any]:
        """
        Format message as OpenAI-compatible chat completion response.

        Args:
            message: The message content to include in the response

        Returns:
            OpenAI-compatible chat completion response dictionary
        """
        return {
            "id": "chatcmpl-sandbox",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "sandbox",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": message,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    def detect_sandbox_history(self, messages: list[dict[str, Any]]) -> bool:
        """
        Check if conversation history contains sandbox login banner.

        This ensures that authenticated sessions cannot continue from
        unauthenticated sandbox sessions, maintaining security isolation.

        Args:
            messages: List of conversation messages to check

        Returns:
            True if sandbox content detected (session must be rejected)
        """
        # Look for the distinctive authentication required header
        sandbox_markers = [
            "# Authentication Required",
            "Authentication Required",
            "Welcome to the LLM Proxy with SSO authentication",
            "chatcmpl-sandbox",
        ]

        for message in messages:
            # Check message content
            content = message.get("content", "")
            if isinstance(content, str):
                for marker in sandbox_markers:
                    if marker in content:
                        return True

            # Check for sandbox completion ID in any metadata
            if message.get("id") == "chatcmpl-sandbox":
                return True

        return False
