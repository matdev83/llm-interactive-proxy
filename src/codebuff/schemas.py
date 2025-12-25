"""
Pydantic models for Codebuff protocol message schemas.

This module defines all client and server message types used in the
Codebuff WebSocket protocol.
"""

# ruff: noqa: N815

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from src.core.domain.chat import ChatMessage, ToolCall
from src.core.interfaces.model_bases import DomainModel

# ============================================================================
# Client Messages (sent from Codebuff client to server)
# ============================================================================


class IdentifyMessage(DomainModel):
    """Client identification message.

    Sent by the client to identify itself and establish a session.
    """

    type: Literal["identify"]
    txid: int
    clientSessionId: str = Field(..., alias="clientSessionId")


class PingMessage(DomainModel):
    """Heartbeat ping message.

    Sent periodically by the client to maintain the connection.
    """

    type: Literal["ping"]
    txid: int


class SubscribeMessage(DomainModel):
    """Subscribe to topics message.

    Sent by the client to subscribe to specific message topics.
    """

    type: Literal["subscribe"]
    txid: int
    topics: list[str]


class UnsubscribeMessage(DomainModel):
    """Unsubscribe from topics message.

    Sent by the client to unsubscribe from specific message topics.
    """

    type: Literal["unsubscribe"]
    txid: int
    topics: list[str]


# ============================================================================
# Action Messages (nested within ActionMessage)
# ============================================================================


class PromptAction(DomainModel):
    """Prompt action for LLM requests.

    Contains the conversation history and parameters for an LLM request.
    """

    type: Literal["prompt"]
    promptId: str = Field(..., alias="promptId")
    prompt: str | None = None
    content: list[ChatMessage] | None = None
    promptParams: dict[str, Any] | None = Field(None, alias="promptParams")
    fingerprintId: str = Field(..., alias="fingerprintId")
    authToken: str | None = Field(None, alias="authToken")
    costMode: str = Field(default="normal", alias="costMode")
    sessionState: dict[str, Any] = Field(..., alias="sessionState")
    toolResults: list[dict[str, Any]] = Field(default_factory=list, alias="toolResults")
    model: str | None = None
    repoUrl: str | None = Field(None, alias="repoUrl")
    agentId: str | None = Field(None, alias="agentId")



class InitAction(DomainModel):
    """Init action for session initialization.

    Initializes a session with file context and project information.
    """

    type: Literal["init"]
    fingerprintId: str = Field(..., alias="fingerprintId")
    authToken: str | None = Field(None, alias="authToken")
    fileContext: dict[str, Any] = Field(..., alias="fileContext")
    repoUrl: str | None = Field(None, alias="repoUrl")


class ActionMessage(DomainModel):
    """Wrapper for action messages.

    Actions are the primary way clients send requests to the server.
    """

    type: Literal["action"]
    txid: int
    data: PromptAction | InitAction


# Union type for all client messages
ClientMessage = (
    IdentifyMessage
    | PingMessage
    | SubscribeMessage
    | UnsubscribeMessage
    | ActionMessage
)


# ============================================================================
# Server Messages (sent from server to Codebuff client)
# ============================================================================


class AckMessage(DomainModel):
    """Acknowledgment message.

    Sent by the server to acknowledge receipt of a client message.
    """

    type: Literal["ack"]
    txid: int | None = None
    success: bool
    error: str | None = None


# ============================================================================
# Server Action Messages (nested within ServerActionMessage)
# ============================================================================


class ResponseChunkAction(DomainModel):
    """Response chunk action for streaming LLM responses.

    Contains a chunk of text from the streaming LLM response.
    """

    type: Literal["response-chunk"]
    userInputId: str = Field(..., alias="userInputId")
    chunk: str


class PromptResponseAction(DomainModel):
    """Prompt response action for final LLM response.

    Sent when the LLM request completes successfully.
    """

    type: Literal["prompt-response"]
    promptId: str = Field(..., alias="promptId")
    sessionState: dict[str, Any] = Field(..., alias="sessionState")
    toolCalls: list[ToolCall] | None = Field(None, alias="toolCalls")
    toolResults: list[dict[str, Any]] | None = Field(None, alias="toolResults")
    output: dict[str, Any] | None = None



class PromptErrorAction(DomainModel):
    """Prompt error action for LLM request errors.

    Sent when an LLM request fails.
    """

    type: Literal["prompt-error"]
    userInputId: str = Field(..., alias="userInputId")
    message: str
    error: str | None = None
    remainingBalance: float | None = Field(None, alias="remainingBalance")


class ActionErrorAction(DomainModel):
    """Action error for general action failures.

    Sent when an action fails for reasons other than LLM errors.
    """

    type: Literal["action-error"]
    message: str
    error: str | None = None
    remainingBalance: float | None = Field(None, alias="remainingBalance")


class InitResponseAction(DomainModel):
    """Init response action for session initialization.

    Sent in response to an init action.
    """

    type: Literal["init-response"]
    message: str | None = None
    agentNames: dict[str, str] | None = Field(None, alias="agentNames")
    usage: float
    remainingBalance: float = Field(..., alias="remainingBalance")
    next_quota_reset: datetime | None = Field(None, alias="next_quota_reset")


class ToolCallRequestAction(DomainModel):
    """Tool call request action (future feature).

    Requests the client to execute a tool call.
    """

    type: Literal["tool-call-request"]
    toolCallId: str = Field(..., alias="toolCallId")
    toolName: str = Field(..., alias="toolName")
    toolArgs: dict[str, Any] = Field(..., alias="toolArgs")


class ReadFilesRequestAction(DomainModel):
    """Read files request action (future feature).

    Requests the client to read specific files.
    """

    type: Literal["read-files-request"]
    requestId: str = Field(..., alias="requestId")
    filePaths: list[str] = Field(..., alias="filePaths")


class ServerActionMessage(DomainModel):
    """Wrapper for server action messages.

    Actions are the primary way the server sends responses to clients.
    """

    type: Literal["action"]
    data: (
        ResponseChunkAction
        | PromptResponseAction
        | PromptErrorAction
        | ActionErrorAction
        | InitResponseAction
        | ToolCallRequestAction
        | ReadFilesRequestAction
    )


# Union type for all server messages
ServerMessage = AckMessage | ServerActionMessage


# ============================================================================
# Helper Models
# ============================================================================


class SessionState(DomainModel):
    """Session state maintained for each client connection.

    This is not a wire protocol message, but an internal data structure.
    """

    session_id: str
    fingerprint_id: str | None = None
    auth_token: str | None = None
    created_at: datetime
    last_seen: datetime
    subscriptions: set[str] = Field(default_factory=set)
    file_context: dict[str, Any] | None = None
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)
    active_requests: dict[str, Any] = Field(default_factory=dict)
