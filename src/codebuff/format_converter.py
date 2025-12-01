"""
Format converter for Codebuff protocol messages.

This module provides conversion between Codebuff message formats and
OpenAI-compatible message formats, as well as creation of Codebuff
server response messages.
"""

from __future__ import annotations

from typing import Any

from src.codebuff.schemas import (
    ActionErrorAction,
    InitResponseAction,
    PromptErrorAction,
    PromptResponseAction,
    ResponseChunkAction,
    ServerActionMessage,
)


class FormatConverter:
    """Converts between Codebuff and OpenAI message formats.

    This class handles:
    - Converting Codebuff conversation messages to OpenAI format
    - Creating response-chunk actions for streaming
    - Creating prompt-response actions for completion
    - Creating error response actions
    - Creating init-response actions
    """

    def codebuff_to_openai(
        self,
        messages: list[dict[str, Any]],
        session_state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Convert Codebuff messages to OpenAI format.

        Args:
            messages: List of Codebuff message dictionaries
            session_state: Session state containing conversation history

        Returns:
            List of OpenAI-compatible message dictionaries with 'role' and 'content'

        The OpenAI format expects messages with:
        - role: "system", "user", or "assistant"
        - content: The message text
        """
        openai_messages: list[dict[str, Any]] = []

        # Process each message and convert to OpenAI format
        for msg in messages:
            # Handle different message formats
            if isinstance(msg, dict):
                # If message already has role and content, use it
                if "role" in msg and "content" in msg:
                    openai_messages.append(
                        {"role": msg["role"], "content": msg["content"]}
                    )
                # If message has text field, assume it's a user message
                elif "text" in msg:
                    openai_messages.append({"role": "user", "content": msg["text"]})
                # If message has message field, extract role and content
                elif "message" in msg:
                    message_data = msg["message"]
                    if isinstance(message_data, dict):
                        role = message_data.get("role", "user")
                        content = message_data.get("content", "")
                        openai_messages.append({"role": role, "content": content})
                    else:
                        # Treat as user message
                        openai_messages.append(
                            {"role": "user", "content": str(message_data)}
                        )
                # If message has type field, handle based on type
                elif "type" in msg:
                    msg_type = msg["type"]
                    if msg_type == "user":
                        content = msg.get("content", msg.get("text", ""))
                        openai_messages.append({"role": "user", "content": content})
                    elif msg_type == "assistant":
                        content = msg.get("content", msg.get("text", ""))
                        openai_messages.append(
                            {"role": "assistant", "content": content}
                        )
                    elif msg_type == "system":
                        content = msg.get("content", msg.get("text", ""))
                        openai_messages.append({"role": "system", "content": content})

        return openai_messages

    def create_response_chunk(
        self,
        user_input_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Create a response-chunk action for streaming.

        Args:
            user_input_id: ID to correlate with the original request
            text: Text chunk to send

        Returns:
            Dictionary representing a ServerActionMessage with ResponseChunkAction
        """
        chunk_action = ResponseChunkAction(
            type="response-chunk", userInputId=user_input_id, chunk=text
        )

        server_message = ServerActionMessage(type="action", data=chunk_action)

        return server_message.model_dump(by_alias=True)

    def create_prompt_response(
        self,
        prompt_id: str,
        session_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a prompt-response action for completion.

        Args:
            prompt_id: ID of the prompt being responded to
            session_state: Updated session state to return

        Returns:
            Dictionary representing a ServerActionMessage with PromptResponseAction
        """
        response_action = PromptResponseAction(
            type="prompt-response",
            promptId=prompt_id,
            sessionState=session_state,
            toolCalls=None,
            toolResults=None,
            output=None,
        )

        server_message = ServerActionMessage(type="action", data=response_action)

        return server_message.model_dump(by_alias=True)

    def create_error_response(
        self,
        user_input_id: str,
        error_message: str,
        remaining_balance: float | None = None,
    ) -> dict[str, Any]:
        """Create a prompt-error action for errors.

        Args:
            user_input_id: ID to correlate with the original request
            error_message: Human-readable error message
            remaining_balance: Optional remaining balance to include

        Returns:
            Dictionary representing a ServerActionMessage with PromptErrorAction
        """
        error_action = PromptErrorAction(
            type="prompt-error",
            userInputId=user_input_id,
            message=error_message,
            error=error_message,
            remainingBalance=remaining_balance,
        )

        server_message = ServerActionMessage(type="action", data=error_action)

        return server_message.model_dump(by_alias=True)

    def create_action_error_response(
        self,
        error_message: str,
        remaining_balance: float | None = None,
    ) -> dict[str, Any]:
        """Create an action-error action for general action failures.

        Args:
            error_message: Human-readable error message
            remaining_balance: Optional remaining balance to include

        Returns:
            Dictionary representing a ServerActionMessage with ActionErrorAction
        """
        error_action = ActionErrorAction(
            type="action-error",
            message=error_message,
            error=error_message,
            remainingBalance=remaining_balance,
        )

        server_message = ServerActionMessage(type="action", data=error_action)

        return server_message.model_dump(by_alias=True)

    def create_init_response(
        self,
        message: str | None = None,
        agent_names: dict[str, str] | None = None,
        usage: float = 0.0,
        remaining_balance: float = float("inf"),
    ) -> dict[str, Any]:
        """Create an init-response action for session initialization.

        Args:
            message: Optional message to include
            agent_names: Optional mapping of agent names
            usage: Usage amount (default 0.0 for MVP)
            remaining_balance: Remaining balance (default unlimited for MVP)

        Returns:
            Dictionary representing a ServerActionMessage with InitResponseAction
        """
        init_action = InitResponseAction(
            type="init-response",
            message=message,
            agentNames=agent_names,
            usage=usage,
            remainingBalance=remaining_balance,
            next_quota_reset=None,
        )

        server_message = ServerActionMessage(type="action", data=init_action)

        return server_message.model_dump(by_alias=True)
