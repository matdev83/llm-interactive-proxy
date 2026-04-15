"""
Internal contracts for request processor phases.

These interfaces define the boundaries between request processing phases
to support the decomposition of the RequestProcessor God Object into
focused, single-responsibility components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.chat import ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope


class ISessionEnricher(ABC):
    """Handles session resolution and client context enrichment."""

    @abstractmethod
    async def enrich(
        self, context: RequestContext, request: ChatRequest
    ) -> tuple[object, ChatRequest]:
        """
        Resolve session and enrich client context.

        Returns:
            tuple[session, possibly_updated_request]: The resolved session object
            and the request, potentially updated with session-specific values
            (agent, VTC flag, etc.).

        This method handles:
        - Session ID resolution
        - Agent normalization (incoming agent vs session agent)
        - Client OS detection and propagation
        - VTC detection and enablement
        - Project directory auto-resolution
        """
        ...


class IRequestSideEffects(ABC):
    """Handles best-effort side effects for request processing."""

    @abstractmethod
    async def apply(
        self, context: RequestContext, session_id: str, request: ChatRequest
    ) -> ChatRequest:
        """
        Apply best-effort side effects and return updated request.

        This method handles:
        - Streaming tool registry updates
        - Memory context injection
        - Memory capture

        All operations are fail-open (log and continue on errors).
        """
        ...


class ICommandHandler(ABC):
    """Handles command processing and command-only flow decisions."""

    @abstractmethod
    async def handle(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ProcessedResult | ResponseEnvelope | StreamingResponseEnvelope:
        """
        Process commands and determine if command-only flow should be taken.

        Returns:
            - ProcessedResult for backend flow (commands were executed but backend call needed)
            - ResponseEnvelope or StreamingResponseEnvelope for command-only flow
              (commands were executed and no backend call needed)

        This method handles:
        - Command processing delegation
        - Artifact preview normalization after command execution
        - Command-only flow detection
        - Special agent-specific command handling (e.g., Cline agent fast-path)
        - Session recording for command-only flows
        """
        ...


class IArtifactService(ABC):
    """Handles artifact preview expansion and compression."""

    @abstractmethod
    def normalize_artifact_previews(self, processed_result: ProcessedResult) -> None:
        """
        Expand and compress artifact previews in tool outputs.

        This method modifies the processed_result in-place:
        - Expands truncated artifact previews in the most recent tool message batch
        - Compresses older expanded previews to preserve context window

        All operations are fail-open (skip on errors, missing paths, etc.).
        """
        ...


class IBackendPreparer(ABC):
    """Handles backend request preparation and validation."""

    @abstractmethod
    async def prepare(
        self,
        context: RequestContext,
        session_id: str,
        request: ChatRequest,
        processed: ProcessedResult,
        *,
        history_compaction_session_allowed: bool = True,
    ) -> ChatRequest | None:
        """
        Prepare backend request and enforce validation limits.

        Returns:
            - ChatRequest: Prepared backend request ready for transformations
            - None: Backend should be skipped (e.g., command-only flow)

        This method handles:
        - Backend request preparation via BackendRequestManager
        - Token limit enforcement (fail-fast on structured validation)
        - Context window validation

        Raises:
            InvalidRequestError: When structured validation fails (input/total token limits)
        """
        ...


class IRequestTransformPipeline(ABC):
    """Handles outbound request transformations."""

    @abstractmethod
    async def transform(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
    ) -> ChatRequest:
        """
        Apply request transformations in fixed order.

        Transformation order (must be preserved):
        1. API key redaction
        2. First user-message suffix append (once per session, when configured)
        3. Edit precision tuning
        4. Tool filtering

        All transformations are fail-open (log and continue on unexpected errors).
        Structured validation failures (from preparation phase) are not handled here.
        """
        ...


class IBackendExecutor(ABC):
    """Handles backend execution and persistence side effects."""

    @abstractmethod
    async def execute(
        self,
        context: RequestContext,
        session: object,
        session_id: str,
        request: ChatRequest,
        original_request: ChatRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Execute backend call and perform required side effects.

        This method handles:
        - Session ID injection into request metadata
        - Backend invocation
        - Session history updates
        - Best-effort fingerprint updates
        - Turn completion (in finally block when replacement state exists)

        The original_request parameter is the user's original request before
        command processing and transformations, needed for session history.
        """
        ...
