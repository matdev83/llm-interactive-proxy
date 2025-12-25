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
from src.core.domain.chat import ChatMessage


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
        messages: list[ChatMessage] | list[dict[str, Any]],
        session_state: dict[str, Any],
    ) -> list[ChatMessage]:
        """Convert Codebuff messages to OpenAI format.

        Args:
            messages: List of Codebuff message objects or dictionaries
            session_state: Session state containing conversation history

        Returns:
            List of OpenAI-compatible ChatMessage objects
        """
        openai_messages: list[ChatMessage] = []

        for msg in messages:
            if not isinstance(msg, ChatMessage):
                # ChatMessage validator will handle text -> content mapping
                msg = ChatMessage(**msg)
            openai_messages.append(msg)

        return openai_messages


    def create_response_chunk(
        self,
        user_input_id: str,
        text: str,
    ) -> ServerActionMessage:
        """Create a response-chunk action for streaming.

        Args:
            user_input_id: ID to correlate with the original request
            text: Text chunk to send

        Returns:
            ServerActionMessage with ResponseChunkAction
        """
        chunk_action = ResponseChunkAction(
            type="response-chunk", userInputId=user_input_id, chunk=text
        )

        return ServerActionMessage(type="action", data=chunk_action)

    def create_prompt_response(
        self,
        prompt_id: str,
        session_state: dict[str, Any],
    ) -> ServerActionMessage:
        """Create a prompt-response action for completion.

        Args:
            prompt_id: ID of the prompt being responded to
            session_state: Updated session state to return

        Returns:
            ServerActionMessage with PromptResponseAction
        """
        response_action = PromptResponseAction(
            type="prompt-response",
            promptId=prompt_id,
            sessionState=session_state,
            toolCalls=None,
            toolResults=None,
            output=None,
        )

        return ServerActionMessage(type="action", data=response_action)

    def create_error_response(
        self,
        user_input_id: str,
        error_message: str,
        remaining_balance: float | None = None,
    ) -> ServerActionMessage:
        """Create a prompt-error action for errors.

        Args:
            user_input_id: ID to correlate with the original request
            error_message: Human-readable error message
            remaining_balance: Optional remaining balance to include

        Returns:
            ServerActionMessage with PromptErrorAction
        """
        error_action = PromptErrorAction(
            type="prompt-error",
            userInputId=user_input_id,
            message=error_message,
            error=error_message,
            remainingBalance=remaining_balance,
        )

        return ServerActionMessage(type="action", data=error_action)

    def create_action_error_response(
        self,
        error_message: str,
        remaining_balance: float | None = None,
    ) -> ServerActionMessage:
        """Create an action-error action for general action failures.

        Args:
            error_message: Human-readable error message
            remaining_balance: Optional remaining balance to include

        Returns:
            ServerActionMessage with ActionErrorAction
        """
        error_action = ActionErrorAction(
            type="action-error",
            message=error_message,
            error=error_message,
            remainingBalance=remaining_balance,
        )

        return ServerActionMessage(type="action", data=error_action)

    def create_init_response(
        self,
        message: str | None = None,
        agent_names: dict[str, str] | None = None,
        usage: float = 0.0,
        remaining_balance: float = float("inf"),
    ) -> ServerActionMessage:
        """Create an init-response action for session initialization.

        Args:
            message: Optional message to include
            agent_names: Optional mapping of agent names
            usage: Usage amount (default 0.0 for MVP)
            remaining_balance: Remaining balance (default unlimited for MVP)

        Returns:
            ServerActionMessage with InitResponseAction
        """
        init_action = InitResponseAction(
            type="init-response",
            message=message,
            agentNames=agent_names,
            usage=usage,
            remainingBalance=remaining_balance,
            next_quota_reset=None,
        )

        return ServerActionMessage(type="action", data=init_action)

