"""Interface for backend and model target resolution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import NamedTuple

from pydantic.types import JsonValue

from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext


class ResolvedTarget(NamedTuple):
    """Result of backend/model resolution.

    Attributes:
        backend: The resolved backend name
        model: The resolved model name
        uri_params: URI parameters extracted from the model string.
            Values must be JSON-serializable (JsonValue).
    """

    backend: str
    model: str
    uri_params: dict[str, JsonValue]


class IBackendModelResolver(ABC):
    """Interface for resolving backend and model targets from requests.

    This interface defines the contract for determining which backend and model
    to use for a given request, including URI parameter extraction and request
    synchronization.
    """

    @abstractmethod
    async def resolve_target(
        self, request: ChatRequest, context: RequestContext | None = None
    ) -> BackendTarget:
        """Resolve backend, model, and URI parameters from request.

        This method applies the following resolution order:
        1. Model alias resolution
        2. Backend prefix parsing from model string
        3. URI parameter extraction
        4. Static routing overrides
        5. Backend discovery/routing

        Args:
            request: The chat completion request
            context: Optional request context

        Returns:
            BackendTarget with backend, model, and URI parameters
        """

    @abstractmethod
    def synchronize_request_with_target(
        self, request: ChatRequest, resolved: BackendTarget
    ) -> ChatRequest:
        """Update request to match resolved backend and model.

        Ensures the request object and its extra_body reflect the resolved
        backend and model information.

        Args:
            request: Original chat request
            resolved: Resolved target information (BackendTarget)

        Returns:
            Updated request with synchronized backend/model
        """
