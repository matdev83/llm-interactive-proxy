"""
Codebuff backend compatibility module.

This module provides WebSocket-based compatibility with the Codebuff protocol,
allowing Codebuff clients to route their LLM requests through this proxy.
"""

__all__ = [
    "CodebuffError",
    "CodebuffConnectionError",
    "CodebuffMessageError",
    "CodebuffValidationError",
    "CodebuffAuthenticationError",
    "CodebuffSessionError",
    "ConnectionManager",
    "FormatConverter",
    "MessageRouter",
    "PromptHandler",
    "CodebuffWebSocketServer",
]

from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import (
    CodebuffAuthenticationError,
    CodebuffConnectionError,
    CodebuffError,
    CodebuffMessageError,
    CodebuffSessionError,
    CodebuffValidationError,
)
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.message_router import MessageRouter
from src.codebuff.server import CodebuffWebSocketServer
