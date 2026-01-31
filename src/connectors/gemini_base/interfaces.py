"""
Strategy interfaces for Gemini OAuth connectors.

This module defines protocols (interfaces) for the Strategy Pattern implementation
that allows different Gemini OAuth backends to be composed from reusable components.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import httpx

    from src.core.domain.chat import CanonicalChatRequest, ChatMessage
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope

from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.orchestrator import StreamWrapper
from src.connectors.gemini_base.streaming_executor import ITokenRefresher
from src.core.common.exceptions import LLMProxyError

if TYPE_CHECKING:
    from src.connectors.gemini_base.models import GeminiOAuthCredentials
else:
    # Runtime import for Protocol checking
    from src.connectors.gemini_base.models import GeminiOAuthCredentials


@runtime_checkable
class ICredentialProvider(Protocol):
    """Protocol for OAuth credential providers.

    Implementations load credentials from different sources:
    - FileCredentialProvider: JSON file (oauth_creds.json)
    - AntigravitySQLiteCredentialProvider: SQLite database (state.vscdb)
    """

    async def load(
        self, force_reload: bool = False, silent: bool = False
    ) -> dict[str, Any] | None:
        """Load OAuth credentials from the source.

        Args:
            force_reload: If True, bypass cache and force reload.
            silent: If True, suppress INFO level logging.

        Returns:
            Credentials dictionary or None if loading failed.
        """
        ...

    def validate(
        self, credentials: dict[str, Any], silent: bool = False
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate.
            silent: If True, suppress INFO level logging.

        Returns:
            Tuple of (is_valid, list_of_errors).
        """
        ...

    def get_path(self) -> Path | None:
        """Get the path to the credentials source.

        Returns:
            Path to the credentials file/database, or None if not applicable.
        """
        ...

    def compute_fingerprint(self, credentials: dict[str, Any]) -> str:
        """Compute a stable fingerprint for the credentials.

        Args:
            credentials: The credentials dictionary.

        Returns:
            SHA-256 hash of the relevant credential fields.
        """
        ...


@runtime_checkable
class IEndpointConfig(Protocol):
    """Protocol for API endpoint configuration.

    Implementations provide endpoint URLs and headers for different backends:
    - StandardCodeAssistEndpoint: cloudcode-pa.googleapis.com
    - AntigravitySandboxEndpoint: daily-cloudcode-pa.sandbox.googleapis.com
    """

    def get_base_url(self) -> str:
        """Get the base URL for the API endpoint.

        Returns:
            The API base URL string.
        """
        ...

    def get_api_headers(self, credentials: dict[str, Any] | None) -> dict[str, str]:
        """Get headers for API requests (used with httpx client).

        Args:
            credentials: Optional credentials dictionary for Authorization header.

        Returns:
            Dictionary of HTTP headers.
        """
        ...

    def get_session_headers(self) -> dict[str, str]:
        """Get headers for AuthorizedSession requests (used with requests library).

        Returns:
            Dictionary of HTTP headers (e.g., custom User-Agent).
        """
        ...


@runtime_checkable
class IRequestBodyBuilder(Protocol):
    """Protocol for building backend-specific request body structures.

    Implementations format the request body differently:
    - StandardRequestBodyBuilder: user_prompt_id format
    - AntigravityRequestBodyBuilder: requestId, userAgent, requestType format
    """

    def build(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        inner_request: dict[str, Any],
        user_prompt_id_generator: Any = None,
    ) -> dict[str, Any]:
        """Build the outer request body wrapper for Code Assist API.

        Args:
            effective_model: The model name to use.
            project_id: The project ID from loadCodeAssist.
            request_data: The original request data (for generating IDs).
            inner_request: The inner request with contents, generationConfig, etc.
            user_prompt_id_generator: Optional callable to generate user_prompt_id.

        Returns:
            Complete request body dict ready to send to the API.
        """
        ...


@runtime_checkable
class IProjectDiscoveryStrategy(Protocol):
    """Protocol for project ID discovery strategies.

    Implementations handle different project discovery flows:
    - FreeTierProjectDiscovery: free-tier onboarding
    - PaidTierProjectDiscovery: paid-tier onboarding
    - AntigravityProjectDiscovery: Antigravity-specific flow
    """

    async def discover(
        self,
        auth_session: Any,
        credentials: dict[str, Any] | None,
        base_url: str,
        cached_project_id: str | None = None,
    ) -> str:
        """Discover or retrieve the project ID for Code Assist API.

        Args:
            auth_session: The authorized session for API calls.
            credentials: OAuth credentials dictionary.
            base_url: The API base URL.
            cached_project_id: Previously discovered project ID, if any.

        Returns:
            The discovered project ID string.
        """
        ...


@runtime_checkable
class IModelDiscoveryStrategy(Protocol):
    """Protocol for model discovery strategies.

    Implementations handle model enumeration differently:
    - ApiModelDiscovery: Calls fetchAvailableModels API
    - FallbackModelDiscovery: Returns hardcoded model list
    """

    async def discover(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
    ) -> list[str]:
        """Discover available models from the backend.

        Args:
            client: The HTTP client for API calls.
            headers: HTTP headers including authorization.
            base_url: The API base URL.

        Returns:
            List of available model names.
        """
        ...

    def get_fallback_models(self) -> list[str]:
        """Get the fallback model list when API discovery fails.

        Returns:
            List of fallback model names.
        """
        ...


@runtime_checkable
class IResponsePostProcessor(Protocol):
    """Protocol for response post-processing.

    Implementations can modify responses after they're received:
    - NoOpResponsePostProcessor: Pass-through, no modifications
    - XmlToolCallPostProcessor: Parse XML tool calls (Antigravity/Claude)
    """

    def process(
        self,
        response: "ResponseEnvelope",
        effective_model: str,
    ) -> "ResponseEnvelope":
        """Post-process a response envelope.

        Args:
            response: The response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed response envelope.
        """
        ...

    async def process_streaming(
        self,
        response: Any,
        effective_model: str,
    ) -> Any:
        """Post-process a streaming response.

        Args:
            response: The streaming response envelope to process.
            effective_model: The model that generated the response.

        Returns:
            The processed streaming response envelope.
        """
        ...


@runtime_checkable
class IHealthCheckStrategy(Protocol):
    """Protocol for health check strategies.

    Implementations perform backend-specific health checks:
    - ApiHealthCheck: Uses fetchAvailableModels endpoint
    - TokenHealthCheck: Only verifies token is refreshable
    """

    async def check(
        self,
        client: "httpx.AsyncClient",
        headers: dict[str, str],
        base_url: str,
        _refresh_token_callback: Any = None,
    ) -> bool:
        """Perform a health check on the backend.

        Args:
            client: The HTTP client for API calls.
            headers: HTTP headers including authorization.
            base_url: The API base URL.
            refresh_token_callback: Optional callback to refresh token.

        Returns:
            True if the backend is healthy, False otherwise.
        """
        ...


@runtime_checkable
class ICredentialCoordinator(Protocol):
    """Protocol for credential lifecycle coordination.

    This interface coordinates credential loading, validation, refresh, and file watching
    for Gemini OAuth connectors. It encapsulates the credential initialization pipeline
    and provides a typed credential state boundary for other services.

    **Data Flow**: This service produces `GeminiOAuthCredentials` instances that flow to:
    - `IModelRegistry` (for API discovery authentication)
    - `IHealthCheckService` (for health check authentication)
    - `IChatCompletionCoordinator` (via connector context for request execution)

    **Service Boundaries**: Isolates credential lifecycle from other connector concerns.
    Supports DI and test seams via protocol-based interface.

    Preconditions: Credentials have been loaded or a refresh attempt has been made.
    Postconditions: Credential state and watcher state are consistent.
    Invariants: Access token presence implies non-expired credentials.
    """

    async def initialize(self, *, gemini_cli_oauth_path: str | None = None) -> None:
        """Load credentials and set initial health state.

        Args:
            gemini_cli_oauth_path: Optional custom path to .gemini directory.

        Raises:
            AuthenticationError: If credentials cannot be loaded or validated.
        """
        ...

    async def validate_runtime(self) -> bool:
        """Return True when credentials are valid for request execution.

        Returns:
            True if credentials are valid and ready for use, False otherwise.
        """
        ...

    async def refresh_if_needed(
        self, 
        *, 
        force_reload: bool = False,
        retry_after_seconds: float | None = None
    ) -> bool:
        """Refresh access token if required and return success.

        Args:
            force_reload: If True, force reload credentials before refresh.
            retry_after_seconds: Optional explicit retry delay suggested by the API.

        Returns:
            True if refresh succeeded or was not needed, False otherwise.
        """
        ...

    async def handle_credentials_file_change(self) -> None:
        """Handle credentials file change event.

        This method is called when the file system watcher detects a change to the
        underlying credentials source.
        """
        ...

    @property
    def credentials(self) -> GeminiOAuthCredentials | None:
        """Return the current credential payload.

        This property provides the typed credential boundary used by other services.
        The returned `GeminiOAuthCredentials` instance can be converted to dict via
        `.to_dict()` for backward compatibility with existing code paths.

        Returns:
            Current credentials or None if not loaded.
        """
        ...


@runtime_checkable
class IModelRegistry(Protocol):
    """Protocol for model discovery, caching, and name mapping.

    This interface handles model enumeration, validation, and alias mapping
    for Gemini connectors. It maintains cached model lists for fast lookups
    and provides public-to-internal name translation.

    **Data Flow**: This service consumes credentials from `ICredentialCoordinator`
    for API discovery and produces model lists for routing and validation.
    Model names flow to `IChatCompletionCoordinator` for request execution.

    **Service Boundaries**: Isolates model discovery and caching from credential
    and execution concerns. Supports DI and test seams via protocol-based interface.

    Preconditions: Credentials are valid when API discovery is attempted.
    Postconditions: Model cache is populated or fallback is applied.
    Invariants: Cached set mirrors available_models list.
    """

    async def ensure_loaded(self) -> None:
        """Load models if not already cached.

        This method performs lazy loading of models via API discovery or fallback list.
        It is safe to call multiple times; subsequent calls are no-ops if already loaded.
        """
        ...

    def validate(self, model_name: str) -> None:
        """Raise if the model is unavailable for this backend.

        Args:
            model_name: The model name to validate.

        Raises:
            BackendError: If the model is not available.
        """
        ...

    def to_public_name(self, model_name: str) -> str:
        """Map internal names to public aliases when required.

        Args:
            model_name: Internal model name.

        Returns:
            Public alias or original name if no mapping exists.
        """
        ...

    def to_internal_name(self, model_name: str) -> str:
        """Map public aliases to internal names when required.

        Args:
            model_name: Public model alias.

        Returns:
            Internal name or original name if no mapping exists.
        """
        ...

    def list_public_models(self) -> list[str]:
        """Return vendor-prefixed models for routing.

        Returns:
            List of public model names with vendor prefixes.
        """
        ...


@runtime_checkable
class IHealthCheckService(Protocol):
    """Protocol for health check and readiness gating.

    This interface performs first-use health checks with existing endpoints
    and records health-checked state without altering connector health semantics.

    **Data Flow**: This service consumes credentials from `ICredentialCoordinator`
    for authentication during health checks. Health state is internal and does
    not flow to other services.

    **Service Boundaries**: Isolates health check logic from credential and
    execution concerns. Supports DI and test seams via protocol-based interface.

    Preconditions: Credentials are valid or have been refreshed.
    Postconditions: Health check state is updated.
    Invariants: A failed health check does not invalidate valid credentials.
    """

    async def ensure_healthy(self) -> None:
        """Perform first use health check if needed.

        This method performs a health check on first use and caches the result.
        Subsequent calls are no-ops if already checked.

        Raises:
            BackendError: If health check fails critically (e.g., auth failure).
        """
        ...


@runtime_checkable
class IChatCompletionCoordinator(Protocol):
    """Protocol for chat completion flow orchestration.

    This interface orchestrates streaming and non-streaming chat completion flows,
    delegating to request preparation, execution, and response accumulation services.

    **Data Flow**: This service orchestrates the flow:
    1. Consumes `CanonicalChatRequest` and `ChatMessage` list from connector facade
    2. Produces `PreparedChatRequest` via `ChatRequestPreparer` (internal)
    3. Delegates to `ICodeAssistOrchestrator` with `PreparedChatRequest` and `ITokenRefresher`
    4. Optionally applies `StreamWrapper` from `IVtcWrapperBuilder` for VTC features
    5. Returns `ResponseEnvelope` or `StreamingResponseEnvelope` to connector facade

    **Service Boundaries**: Isolates chat completion orchestration from credential,
    model, and health concerns. Supports DI and test seams via protocol-based interface.

    Preconditions: Credential validation and health checks are completed.
    Postconditions: Response envelopes match existing behavior.
    Invariants: Streaming responses preserve chunk order and termination.
    """

    async def execute(
        self,
        request_data: "CanonicalChatRequest",
        processed_messages: list["ChatMessage"],
        *,
        effective_model: str,
    ) -> "ResponseEnvelope | StreamingResponseEnvelope":
        """Return a streaming or non-streaming response envelope.

        Args:
            request_data: The canonical chat request.
            processed_messages: Pre-processed chat messages.
            effective_model: The model name to use.

        Returns:
            ResponseEnvelope for non-streaming, StreamingResponseEnvelope for streaming.

        Raises:
            BackendError: If execution fails.
            InvalidRequestError: If request is invalid.
        """
        ...


@runtime_checkable
class IErrorMapper(Protocol):
    """Protocol for error normalization to LLMProxyError hierarchy.

    This interface maps connector exceptions to stable LLMProxy error categories
    while preserving status codes and error semantics for resilience layer compatibility.

    **Data Flow**: This service transforms exceptions:
    - Consumes raw exceptions (`Exception`) caught within connector boundaries
    - Produces normalized `LLMProxyError` subclasses for resilience layer compatibility
    - Used by `IChatCompletionCoordinator` and connector facade for error handling

    **Service Boundaries**: Isolates error mapping logic from execution concerns.
    Supports DI and test seams via protocol-based interface.

    Preconditions: Error is caught within connector boundary.
    Postconditions: Returned error is an LLMProxyError subclass.
    Invariants: Status code and error code remain consistent with existing behavior.
    """

    def map_exception(self, error: Exception, *, backend_name: str) -> LLMProxyError:
        """Normalize exceptions without changing status mapping.

        Maps `AuthenticationError`, `BackendError`, `InvalidRequestError`, and `HTTPException`
        to stable LLMProxy error categories. Converts unexpected exceptions to `BackendError`
        with logging and `exc_info=True`.

        **Important**: This method returns LLMProxyError instances (does not raise them),
        except for `HTTPException` which is raised for FastAPI compatibility. Callers are
        responsible for raising the returned exceptions.

        Args:
            error: The exception to map.
            backend_name: Name of the backend for error context.

        Returns:
            Normalized LLMProxyError subclass with preserved status semantics.

        Raises:
            HTTPException: FastAPI exceptions are re-raised for FastAPI's exception handling.
        """
        ...


@runtime_checkable
class IVtcWrapperBuilder(Protocol):
    """Protocol for optional VTC streaming wrapper assembly.

    This interface builds StreamWrapper instances for VTC (tool call) responses
    when enabled, returning None when VTC is disabled or dependencies are unavailable.

    **Data Flow**: This service produces `StreamWrapper` functions that flow to
    `ICodeAssistOrchestrator.run_streaming()` as the optional `stream_wrapper` parameter.
    The wrapper transforms `AsyncIterator[ProcessedResponse]` streams to enable
    VTC (tool call) processing features.

    **Service Boundaries**: Isolates optional VTC feature assembly. Returns None
    when VTC is disabled or dependencies unavailable, allowing graceful degradation.
    Supports DI and test seams via protocol-based interface.

    Preconditions: Request data is validated and includes VTC flags if applicable.
    Postconditions: Wrapper is pure and does not mutate the stream.
    Invariants: Wrapper does not alter chunk ordering.
    """

    def build(
        self,
        request_data: "CanonicalChatRequest",
        *,
        effective_model: str,
    ) -> StreamWrapper | None:
        """Return a wrapper when VTC is enabled, otherwise None.

        This is an optional feature - implementations should return None when:
        - VTC is disabled in the request
        - Required DI dependencies (ToolCallReactorService, etc.) are unavailable
        - The feature is not supported for the given model

        Args:
            request_data: The canonical chat request.
            effective_model: The model name being used.

        Returns:
            StreamWrapper function if VTC is enabled, None otherwise.
        """
        ...


@runtime_checkable
class ICodeAssistOrchestrator(Protocol):
    """Protocol for streaming and non-streaming orchestration.

    This interface owns streaming and non-streaming orchestration with post-processing.
    It runs streaming requests with prefetch behavior and optional wrappers, and
    accumulates streaming responses for non-streaming callers.

    **Data Flow**: This service orchestrates execution:
    1. Consumes `PreparedChatRequest` from `IChatCompletionCoordinator`
    2. Uses `ITokenRefresher` for token refresh during execution
    3. Optionally applies `StreamWrapper` (from `IVtcWrapperBuilder`) to transform stream
    4. Returns `StreamingResponseEnvelope` or `ResponseEnvelope` to coordinator

    **Service Boundaries**: Isolates execution orchestration from request preparation
    and response accumulation. Supports DI and test seams via protocol-based interface.

    Preconditions: Prepared request is valid and token refresher is available.
    Postconditions: Envelope is populated with stable response shape.
    Invariants: Stream ordering matches the backend delivery order.
    """

    async def run_streaming(
        self,
        *,
        prepared: PreparedChatRequest,
        url: str,
        token_refresher: ITokenRefresher,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        stream_wrapper: StreamWrapper | None = None,
    ) -> "StreamingResponseEnvelope":
        """Execute a streaming request and return a streaming envelope.

        The `stream_wrapper` parameter is optional and enables VTC (tool call) features
        when provided. It wraps the response stream to intercept and process tool calls.

        Args:
            prepared: The prepared chat request (data boundary from request preparation).
            url: The API endpoint URL.
            token_refresher: Token refresh interface for runtime token management.
            thought_signature_callback: Optional callback for thought signatures.
                Receives list of raw tool call dictionaries and session ID.
            key_name: Optional key name for logging.
            stream_wrapper: Optional wrapper function for stream processing (VTC feature).

        Returns:
            StreamingResponseEnvelope with async iterator of ProcessedResponse chunks.
        """
        ...

    async def run_non_streaming(
        self,
        *,
        prepared: PreparedChatRequest,
        url: str,
        token_refresher: ITokenRefresher,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
    ) -> "ResponseEnvelope":
        """Execute via streaming and accumulate into a response envelope.

        Args:
            prepared: The prepared chat request (data boundary from request preparation).
            url: The API endpoint URL.
            token_refresher: Token refresh interface for runtime token management.
            thought_signature_callback: Optional callback for thought signatures.
                Receives list of raw tool call dictionaries and session ID.
            key_name: Optional key name for logging.

        Returns:
            ResponseEnvelope with accumulated response content.
        """
        ...


__all__ = [
    "IChatCompletionCoordinator",
    "ICodeAssistOrchestrator",
    "ICredentialCoordinator",
    "ICredentialProvider",
    "IEndpointConfig",
    "IErrorMapper",
    "IHealthCheckService",
    "IHealthCheckStrategy",
    "IModelDiscoveryStrategy",
    "IModelRegistry",
    "IProjectDiscoveryStrategy",
    "IRequestBodyBuilder",
    "IResponsePostProcessor",
    "IVtcWrapperBuilder",
]
