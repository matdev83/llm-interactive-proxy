"""
Error mapping service for Gemini OAuth connectors.

This module provides GeminiErrorMapper which normalizes connector exceptions
to LLMProxyError hierarchy while preserving status codes and error semantics.
"""

import logging

from fastapi import HTTPException

from src.connectors.gemini_base.interfaces import IErrorMapper
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    LLMProxyError,
)

logger = logging.getLogger(__name__)


class GeminiErrorMapper(IErrorMapper):
    """Service for error normalization to LLMProxyError hierarchy.

    This service maps connector exceptions to stable LLMProxy error categories
    while preserving status codes and error semantics for resilience layer compatibility.

    Preconditions: Error is caught within connector boundary.
    Postconditions: Returned error is an LLMProxyError subclass.
    Invariants: Status code and error code remain consistent with existing behavior.
    """

    def __init__(self, logger_instance: logging.Logger | None = None) -> None:
        """Initialize the error mapper.

        Args:
            logger_instance: Optional logger instance (defaults to module logger).
        """
        self._logger = logger_instance or logger

    def map_exception(self, error: Exception, *, backend_name: str) -> LLMProxyError:
        """Normalize exceptions without changing status mapping.

        Args:
            error: The exception to map.
            backend_name: Name of the backend for error context.

        Returns:
            Normalized LLMProxyError subclass with preserved status semantics.

        Raises:
            HTTPException: FastAPI exceptions are re-raised for FastAPI's exception handling.
        """
        # Re-raise HTTP exceptions directly (FastAPI exception)
        # These must be raised, not returned, for FastAPI's exception handling
        if isinstance(error, HTTPException):
            raise error

        # Return LLMProxyError subclasses as-is (already normalized)
        # Callers will raise these exceptions
        if isinstance(error, AuthenticationError):
            return error
        if isinstance(error, BackendError):
            return error
        if isinstance(error, InvalidRequestError):
            return error

        # Convert other exceptions to BackendError
        # Log with exc_info=True before mapping
        self._logger.error(
            f"Error in {backend_name} chat_completions: {error}",
            exc_info=True,
        )
        return BackendError(
            message=f"{backend_name} chat completion failed: {error!s}",
            backend_name=backend_name,
        )
