"""
Sandbox handler for unauthenticated SSO requests.

This module provides the SandboxHandler class that generates restricted
responses for unauthenticated users, guiding them through the SSO
authentication process.
"""

import time
from typing import Any

from pydantic import BaseModel

from src.core.auth.sso.database import TokenRepository


class ChatCompletionMessage(BaseModel):
    """OpenAI chat completion message."""

    role: str
    content: str


class ChatCompletionChoice(BaseModel):
    """OpenAI chat completion choice."""

    index: int
    message: ChatCompletionMessage
    finish_reason: str


class ChatCompletionUsage(BaseModel):
    """OpenAI chat completion usage."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    id: str
    object: str
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


class SandboxHandler:
    """Handles requests from unauthenticated users."""

    def __init__(self, auth_url: str, token_repository: TokenRepository | None = None):
        """
        Initialize sandbox handler.

        Args:
            auth_url: Base URL for SSO authentication endpoint
            token_repository: Repository for generating one-off login tokens
        """
        self.auth_url = auth_url
        self.token_repository = token_repository

    async def generate_login_banner(
        self, auth_url: str | None = None, agent_token_id: str | None = None
    ) -> ChatCompletionResponse:
        """
        Generate a chat completion response containing login instructions.

        The banner includes:
            - Welcome message
            - Authentication URL (with one-off token if enabled)
            - Instructions to configure agent after auth
            - Note that session cannot continue after auth

        Args:
            auth_url: Optional override for authentication URL.
                     If not provided, uses the instance's auth_url.
            agent_token_id: Optional existing agent token ID for re-authentication.
                           If provided, the SSO flow will update this token instead
                           of creating a new one.

        Returns:
            OpenAI-compatible chat completion response with login banner
        """
        base_url = auth_url or self.auth_url

        # Append one-off token if repository is available
        final_url = base_url
        if self.token_repository:
            try:
                token = await self.token_repository.create_login_token(
                    agent_token_id=agent_token_id
                )
                separator = "&" if "?" in base_url else "?"
                final_url = f"{base_url}{separator}token={token}"
            except Exception:
                # Fallback to base URL if token generation fails
                pass

        # Determine if this is re-authentication or new authentication
        if agent_token_id:
            message = (
                "# Re-Authentication Required\n\n"
                "Your SSO session has expired and needs to be renewed.\n\n"
                "## Steps to Re-Authenticate:\n\n"
                f"1. Open this URL in your browser: {final_url}\n"
                "2. Complete the SSO authentication with your identity provider\n"
                "3. Your existing agent token will be automatically renewed\n"
                "4. No reconfiguration needed - your agent will continue working\n\n"
                "## Important Notes:\n\n"
                "- This conversation session cannot continue after authentication\n"
                "- Your existing token will be reactivated (no need to reconfigure)\n"
                "- Start a new conversation after re-authenticating\n"
                "- Your token will remain valid until your next SSO session expires\n\n"
                "Please re-authenticate to continue."
            )
        else:
            message = (
                "# Authentication Required\n\n"
                "Welcome to the LLM Proxy with SSO authentication.\n\n"
                "To use this proxy, you need to authenticate via Single Sign-On (SSO).\n\n"
                "## Steps to Authenticate:\n\n"
                f"1. Open this URL in your browser: {final_url}\n"
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

    def format_as_completion_response(self, message: str) -> ChatCompletionResponse:
        """
        Format message as OpenAI-compatible chat completion response.

        Args:
            message: The message content to include in the response

        Returns:
            OpenAI-compatible chat completion response
        """
        return ChatCompletionResponse(
            id="chatcmpl-sandbox",
            object="chat.completion",
            created=int(time.time()),
            model="sandbox",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionMessage(role="assistant", content=message),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
        )

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
            "authentication required",
            "welcome to the llm proxy with sso authentication",
            "chatcmpl-sandbox",
            "please authenticate at",
            "authenticate to continue",
        ]

        for message in messages:
            # Check message content
            content = message.get("content", "")
            if isinstance(content, str):
                content_lower = content.lower()
                for marker in sandbox_markers:
                    if marker in content_lower:
                        return True

            # Check for sandbox completion ID in any metadata
            if message.get("id") == "chatcmpl-sandbox":
                return True

        return False
