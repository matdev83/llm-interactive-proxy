"""
Base class for Gemini OAuth connectors.
"""

import abc
import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import requests  # type: ignore[import-untyped]
from fastapi import HTTPException

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
)
from src.core.domain.session_key import SessionKey

if TYPE_CHECKING:

    pass

from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.gemini import GeminiApiConfig, GeminiBackend
from src.connectors.gemini_base.chat_completion_coordinator import (
    GeminiChatCompletionCoordinator,
)
from src.connectors.gemini_base.chat_request_preparer import (
    ChatRequestPreparer,
)
from src.connectors.gemini_base.config import (
    CODE_ASSIST_ENDPOINT,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    GracefulDegradationConfig,
)
from src.connectors.gemini_base.credential_coordinator import (
    GeminiCredentialCoordinator,
)
from src.connectors.gemini_base.credential_loader import CredentialLoader
from src.connectors.gemini_base.credentials import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
)

# Strategy interfaces and implementations
from src.connectors.gemini_base.endpoints import StandardCodeAssistEndpoint
from src.connectors.gemini_base.error_mapper import GeminiErrorMapper
from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState
from src.connectors.gemini_base.generation_config_builder import (
    GenerationConfigBuilder,
    convert_from_code_assist_format,
)
from src.connectors.gemini_base.google_auth_adapter import (
    GoogleAuthProvider,
    get_default_google_auth_provider,
)
from src.connectors.gemini_base.graceful_degradation import (
    GracefulDegradationManager,
    set_model_cooldown,
)
from src.connectors.gemini_base.health_check_service import GeminiHealthCheckService
from src.connectors.gemini_base.interfaces import (
    IChatCompletionCoordinator,
    ICredentialCoordinator,
    ICredentialProvider,
    IEndpointConfig,
    IErrorMapper,
    IHealthCheckService,
    IModelDiscoveryStrategy,
    IModelRegistry,
    IProjectDiscoveryStrategy,
    IRequestBodyBuilder,
    IResponsePostProcessor,
    IVtcWrapperBuilder,
)
from src.connectors.gemini_base.model_discovery import ApiModelDiscovery
from src.connectors.gemini_base.model_registry import GeminiModelRegistry
from src.connectors.gemini_base.model_validation import (
    GOOGLE_VENDOR_PREFIX,
)
from src.connectors.gemini_base.orchestrator import (
    CodeAssistOrchestrator,
    StreamWrapper,
)
from src.connectors.gemini_base.policies import (
    AuthRefreshPolicy,
    IAuthRefreshPolicy,
    IRetryPolicy,
    RateLimitRetryPolicy,
)
from src.connectors.gemini_base.prompt_limiter import (
    enforce_prompt_limit,
    get_prompt_limit,
    normalize_model_key,
)
from src.connectors.gemini_base.request_builders import StandardRequestBodyBuilder
from src.connectors.gemini_base.response_accumulator import (
    StreamingResponseAccumulator,
    response_envelope_to_stream_chunk,
)
from src.connectors.gemini_base.response_processors import NoOpResponsePostProcessor
from src.connectors.gemini_base.response_text_extractor import (
    extract_generated_text_from_response,
)
from src.connectors.gemini_base.retry_delay_parser import (
    extract_retry_delay as _extract_retry_delay_impl,
)
from src.connectors.gemini_base.retry_delay_parser import (
    parse_duration_string as _parse_duration_string_impl,
)
from src.connectors.gemini_base.retry_delay_parser import (
    parse_retry_from_message as _parse_retry_from_message_impl,
)
from src.connectors.gemini_base.streaming_executor import (
    StreamingExecutor,
)
from src.connectors.gemini_base.thought_signature_service import (
    ThoughtSignatureService,
    get_default_thought_signature_service,
)
from src.connectors.gemini_base.token_estimator import (
    TiktokenEstimator,
    get_default_token_estimator,
)
from src.connectors.gemini_base.token_manager import TokenManager
from src.connectors.gemini_base.tool_sanitizer import sanitize_code_assist_tools
from src.connectors.gemini_base.user_prompt_id_generator import (
    generate_user_prompt_id as _generate_user_prompt_id_impl,
)
from src.connectors.gemini_base.vtc_wrapper_builder import GeminiVtcWrapperBuilder
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin
from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.models_listing import ModelInfo, ModelsListingResponse
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["GeminiOAuthBaseConnector", "GOOGLE_VENDOR_PREFIX"]


class GeminiOAuthBaseConnector(GeminiBackend, GeminiCodeAssistMixin, abc.ABC):
    """Base class for Gemini OAuth connectors.

    **Observability and Security Invariants**:
    This refactoring preserves all observability and security invariants:
    - **Wire Captures**: Request/response payloads are captured via the same code paths
      (orchestrator -> streaming executor) with identical request/response shapes. The
      coordinator delegates to the same orchestrator that performs wire captures.
    - **Logging Structure**: All logger calls remain unchanged - coordinator methods use
      the same logger instances and log at the same levels. Logging structure and content
      are preserved through delegation.
    - **Secret Redaction**: Credential access patterns are unchanged - credentials are
      accessed through the same properties and methods (_oauth_credentials, credential
      coordinator) that perform redaction. The coordinator uses the same credential
      coordinator that handles secret redaction.
    """

    default_prompt_limit: int | None = DEFAULT_CODE_ASSIST_PROMPT_LIMIT
    prompt_limit_overrides: dict[str, int] = {}
    # Claude models have 200K context windows; Gemini 2.5/3.x series has 1M.
    # Subclasses can extend these prefixes.
    prompt_limit_prefix_overrides: tuple[tuple[str, int], ...] = (
        ("claude", 200_000),
        ("gemini-2.5", 1_000_000),
        ("gemini-3", 1_000_000),
    )

    @property
    def has_static_credentials(self) -> bool:
        return False

    # Mapping from public aliases (without vendor prefix) to internal model names
    # Subclasses can override this class attribute to provide connector-specific mappings.
    # When accessed via self._public_to_internal_model_map, Python's attribute resolution
    # will correctly find the subclass's version if overridden. This mapping is passed
    # to the model registry during initialization (line 454).
    _public_to_internal_model_map: dict[str, str] = {
        "gemini-3-pro": "gemini-3-pro-preview",
    }

    _project_id: str | None = None

    # NOTE: Class-level _thought_signature_cache has been removed to fix
    # cross-session leakage risk. Thought signature management is now handled
    # entirely by the injected ThoughtSignatureService (DI pattern).

    @staticmethod
    def _normalize_model_key(model_name: str) -> str:
        """Normalize model identifiers for prompt-limit lookups."""
        return normalize_model_key(model_name)

    @staticmethod
    def _sanitize_model_name(model_name: str) -> str:
        """Sanitize model name to prevent internal leaks."""
        if not model_name:
            return "unknown"
        # If it's an internal model name, map it to a generic one or the requested one
        if "code-assist-model" in model_name:
            return "gemini-2.5-pro"  # Default fallback for code assist
        return model_name

    def _inject_thought_signatures(
        self, canonical_request: Any, session_id: str
    ) -> None:
        """Inject stored thought_signatures into tool_calls that are missing them.

        Clients like Droid don't preserve extra_content when storing tool calls,
        so we need to look up and inject the thought_signature from our server-side cache.

        Delegates to injected ThoughtSignatureService for implementation.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID for cache key lookup
        """
        # Use injected service for thought signature management
        if self._thought_signature_service is not None:
            self._thought_signature_service.inject_signatures(
                canonical_request,
                session_id,
            )

    def _log_tool_call_signature_state(
        self, canonical_request: Any, session_id: str, effective_model: str
    ) -> None:
        """Log presence/absence of thought signatures on assistant tool calls.

        Delegates to injected ThoughtSignatureService for implementation.
        """
        if self._thought_signature_service is not None:
            self._thought_signature_service.log_signature_state(
                canonical_request, session_id, effective_model
            )

    @staticmethod
    def _extract_generated_text_from_response(response_payload: Any) -> str:
        """Extract concatenated text content from a Gemini Code Assist response.

        Delegates to response_text_extractor module.
        """
        return extract_generated_text_from_response(response_payload)

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str,
        # Optional strategy injection for composition
        credential_provider: ICredentialProvider | None = None,
        endpoint_config: IEndpointConfig | None = None,
        request_body_builder: IRequestBodyBuilder | None = None,
        project_discovery: IProjectDiscoveryStrategy | None = None,
        model_discovery: IModelDiscoveryStrategy | None = None,
        response_post_processor: IResponsePostProcessor | None = None,
        # Injectable infrastructure services (new)
        token_manager: TokenManager | None = None,
        request_counter: DailyRequestCounter | None = None,
        file_watcher_state: FileWatcherState | None = None,
        graceful_degradation: GracefulDegradationManager | None = None,
        # New injectable services for SOLID compliance
        thought_signature_service: ThoughtSignatureService | None = None,
        token_estimator: TiktokenEstimator | None = None,
        google_auth_provider: GoogleAuthProvider | None = None,
        streaming_executor: StreamingExecutor | None = None,
        retry_policy: IRetryPolicy | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
    ) -> None:
        super().__init__(
            client, config, translation_service
        )  # Pass translation_service to super
        self.name = name
        self.is_functional = False
        # _oauth_credentials is accessed via property, stored in __dict__ for backward compatibility
        self._credentials_path: Path | None = None
        self._last_modified: float = 0
        self.translation_service = translation_service
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0

        # Strategy objects for pluggable behavior
        # When not provided, use defaults (backward compatible)
        self._credential_provider = credential_provider
        self._endpoint_config = endpoint_config or StandardCodeAssistEndpoint()
        self._request_body_builder = (
            request_body_builder or StandardRequestBodyBuilder()
        )
        self._project_discovery = project_discovery
        self._model_discovery = model_discovery or ApiModelDiscovery()
        self._response_post_processor = (
            response_post_processor or NoOpResponsePostProcessor()
        )

        # Token management (composed or injected)
        self._token_manager = token_manager or TokenManager()

        # New injectable services for SOLID compliance
        self._thought_signature_service: ThoughtSignatureService = (
            thought_signature_service or get_default_thought_signature_service()
        )
        self._token_estimator = token_estimator or get_default_token_estimator()
        self._google_auth_provider = (
            google_auth_provider or get_default_google_auth_provider()
        )
        # Request counter (injected or default)
        self._request_counter: DailyRequestCounter | None = request_counter
        if self._request_counter is None:
            self._request_counter = DailyRequestCounter(
                persistence_path=Path("var/state/gemini_oauth_request_count.json"),
                limit=1000,
            )

        # Chat request preparation (composed, uses injected services)
        # Uses narrow interfaces for SOLID compliance - connector implements
        # IConnectorContext, IMessageConverter, IPromptLimiter, IRequestBodyBuilder
        self._chat_preparer = ChatRequestPreparer(
            connector_context=self,
            message_converter=self,
            prompt_limiter=self,
            request_body_builder=self,
            request_counter=self._request_counter,
            translation_service=translation_service,
            google_auth_provider=self._google_auth_provider,
            thought_signature_service=self._thought_signature_service,
        )

        # Streaming executor (injected or lazily created)
        self._streaming_executor_instance = streaming_executor
        self._retry_policy: IRetryPolicy = retry_policy or RateLimitRetryPolicy(
            retry_delay_extractor=self._extract_retry_delay,
            is_rate_limit_like=self._is_rate_limit_like_error,
            max_attempts=1,
        )
        self._auth_refresh_policy: IAuthRefreshPolicy = (
            auth_refresh_policy or AuthRefreshPolicy()
        )
        self._orchestrator_instance: CodeAssistOrchestrator | None = None

        # File watching (composed or injected)
        self._file_watcher_state = file_watcher_state or FileWatcherState()
        # Store reference to the main event loop for thread-safe operations
        self._main_loop: asyncio.AbstractEventLoop | None = None
        # Flag to track if quota has been exceeded
        self._quota_exceeded = False

        # Health checks are enabled by default and controlled by the AppConfig
        self._health_checked: bool = not self.config.get("disable_health_checks", False)

        # Set custom .gemini directory path (will be set in initialize)
        self.gemini_cli_oauth_path: str | None = None

        # Initialize graceful degradation via manager (injected or default)
        # Force disabled by default to comply with new Resilience Layer architecture
        # Fallbacks/Retries are handled by BackendService + ResilienceCoordinator
        if graceful_degradation is not None:
            self._graceful_degradation = graceful_degradation
        else:
            degradation_config = GracefulDegradationConfig.from_config(self.config)
            degradation_config.enabled = False
            self._graceful_degradation = GracefulDegradationManager(
                config=degradation_config
            )
        self._recovery_probe_task: asyncio.Task[Any] | None = None

        # Cache for fast model validation lookups
        self._available_models_set: set[str] = set()
        # Flag to track if models were loaded from API (vs hardcoded fallback)
        self._models_from_api: bool = False

        # Keep track of background tasks to prevent garbage collection
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Prompt-limit configuration (overrides can be supplied by subclasses)
        self._default_prompt_limit = getattr(
            self, "default_prompt_limit", DEFAULT_CODE_ASSIST_PROMPT_LIMIT
        )
        raw_overrides = dict(getattr(self, "prompt_limit_overrides", {}) or {})
        self._prompt_limit_overrides: dict[str, int] = {}
        for key, limit in raw_overrides.items():
            if limit is None:
                continue
            try:
                normalized_key = self._normalize_model_key(key)
                limit_value = int(limit)
            except (ValueError, TypeError):
                continue
            if limit_value > 0:
                self._prompt_limit_overrides[normalized_key] = limit_value

        raw_prefix_overrides_attr = getattr(self, "prompt_limit_prefix_overrides", None)
        raw_prefix_overrides = tuple(raw_prefix_overrides_attr or ())
        normalized_prefixes: list[tuple[str, int]] = []
        for prefix, limit in cast(tuple[tuple[str, int], ...], raw_prefix_overrides):
            if limit is None:
                continue
            try:
                normalized_prefix = self._normalize_model_key(prefix)
                limit_value = int(limit)
            except (ValueError, TypeError):
                continue
            if limit_value > 0:
                normalized_prefixes.append((normalized_prefix, limit_value))
        self._prompt_limit_prefix_overrides = tuple(normalized_prefixes)
        # Credential tracking
        self._credentials_fingerprint: str | None = None
        self._credentials_file_hash: str | None = None
        self._last_credentials_event_hash: str | None = None
        self._last_credentials_event_log_ts: float = 0.0
        self._last_credentials_event_mtime: float | None = None

        # Initialize coordinator services (with DI fallback)
        # Try to resolve from DI first, fallback to local construction
        provider = None
        try:
            from src.core.di.services import get_service_provider

            provider = get_service_provider()
        except (RuntimeError, AttributeError, ImportError) as exc:
            # DI not available or provider not initialized, will construct locally
            # RuntimeError: provider not initialized or event loop issues
            # AttributeError: provider object malformed
            # ImportError: module import failure
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DI service provider not available during connector initialization, using local construction: %s",
                    type(exc).__name__,
                    exc_info=True,
                )
        except Exception as exc:
            # Unexpected exception - log at WARNING level for visibility
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Unexpected error accessing DI service provider during connector initialization: %s",
                    type(exc).__name__,
                    exc_info=True,
                )

        # Credential coordinator
        self._credential_coordinator: ICredentialCoordinator | None = None
        if provider:
            try:
                self._credential_coordinator = provider.get_service(ICredentialCoordinator)  # type: ignore[type-abstract]
            except RuntimeError as exc:
                logger.debug(
                    "DI service missing during connector initialization (%s); using local fallback for credential coordinator",
                    exc,
                )
        if not self._credential_coordinator:
            # Fallback: construct locally
            self._credential_coordinator = GeminiCredentialCoordinator(
                token_manager=self._token_manager,
                file_watcher_state=self._file_watcher_state,
            )

        # Model registry
        self._model_registry: IModelRegistry | None = None
        if provider:
            try:
                self._model_registry = provider.get_service(IModelRegistry)  # type: ignore[type-abstract]
            except RuntimeError as exc:
                logger.debug(
                    "DI service missing during connector initialization (%s); using local fallback for model registry",
                    exc,
                )
        if not self._model_registry:
            # Fallback: construct locally
            self._model_registry = GeminiModelRegistry(
                model_discovery=self._model_discovery,
                endpoint_config=self._endpoint_config,
                credential_coordinator=self._credential_coordinator,
                http_client=self.client,
                public_to_internal_map=self._public_to_internal_model_map,
                backend_name=getattr(self, "backend_type", "gemini-oauth"),
            )

        # Health check service
        self._health_check_service: IHealthCheckService | None = None
        if provider:
            try:
                self._health_check_service = provider.get_service(IHealthCheckService)  # type: ignore[type-abstract]
            except RuntimeError as exc:
                logger.debug(
                    "DI service missing during connector initialization (%s); using local fallback for health check service",
                    exc,
                )
        if not self._health_check_service:
            # Fallback: construct locally
            disable_health_checks = self.config.get("disable_health_checks", False)
            self._health_check_service = GeminiHealthCheckService(
                credential_coordinator=self._credential_coordinator,
                endpoint_config=self._endpoint_config,
                http_client=self.client,
                backend_name=getattr(self, "backend_type", "gemini-oauth"),
                disable_health_checks=disable_health_checks,
            )

        # Error mapper
        self._error_mapper: IErrorMapper | None = None
        if provider:
            try:
                self._error_mapper = provider.get_service(IErrorMapper)  # type: ignore[type-abstract]
            except RuntimeError as exc:
                logger.debug(
                    "DI service missing during connector initialization (%s); using local fallback for error mapper",
                    exc,
                )
        if not self._error_mapper:
            # Fallback: construct locally
            self._error_mapper = GeminiErrorMapper()

        # VTC wrapper builder
        self._vtc_wrapper_builder: IVtcWrapperBuilder | None = None
        if provider:
            try:
                self._vtc_wrapper_builder = provider.get_service(IVtcWrapperBuilder)  # type: ignore[type-abstract]
            except RuntimeError as exc:
                logger.debug(
                    "DI service missing during connector initialization (%s); using local fallback for VTC wrapper builder",
                    exc,
                )
        if not self._vtc_wrapper_builder:
            # Fallback: construct locally
            self._vtc_wrapper_builder = GeminiVtcWrapperBuilder(
                backend_type=getattr(self, "backend_type", "gemini-oauth"),
            )

        # Chat completion coordinator (created lazily in property to avoid circular deps)
        self._chat_completion_coordinator: IChatCompletionCoordinator | None = None

    def is_backend_functional(self) -> bool:
        """Check if backend is functional and ready to handle requests.

        Returns:
            bool: True if backend is functional, False otherwise
        """
        return (
            self.is_functional
            and not self._initialization_failed
            and len(self._credential_validation_errors) == 0
        )

    @property
    def _oauth_credentials(self) -> dict[str, Any] | None:  # type: ignore[redeclaration]
        """Get current OAuth credentials - implements IConnectorContext.

        This property bridges the credential coordinator to the IConnectorContext interface.
        For backward compatibility, also syncs with the instance variable.
        """
        # Sync from coordinator if available
        if self._credential_coordinator and self._credential_coordinator.credentials:
            creds_dict = self._credential_coordinator.credentials.to_dict()
            # Keep instance variable in sync for backward compatibility
            self.__dict__["_oauth_credentials"] = creds_dict
            return creds_dict
        # Fallback to instance variable for backward compatibility
        return self.__dict__.get("_oauth_credentials")

    @_oauth_credentials.setter
    def _oauth_credentials(self, value: dict[str, Any] | None) -> None:  # type: ignore[redeclaration]
        """Set OAuth credentials - for backward compatibility with CredentialLoader."""
        self.__dict__["_oauth_credentials"] = value
        # Note: Coordinator manages its own state, so we don't sync back to it here
        # The coordinator will update its state during initialize/refresh operations

    @property
    def _streaming_executor(self) -> StreamingExecutor:
        """Get or lazily create the streaming executor.

        The executor is created lazily to allow the connector to fully
        initialize before the executor is used.
        """
        if self._streaming_executor_instance is None:
            self._streaming_executor_instance = StreamingExecutor(
                translation_service=self.translation_service,
                token_estimator=self._token_estimator,
                google_auth_provider=self._google_auth_provider,
                retry_delay_extractor=self,  # Connector implements IRetryDelayExtractor
                auth_refresh_policy=self._auth_refresh_policy,
                retry_policy=self._retry_policy,
                backend_type=self.backend_type,
            )
        return self._streaming_executor_instance

    @property
    def _orchestrator(self) -> CodeAssistOrchestrator:
        """Get or lazily create the orchestration helper."""
        if self._orchestrator_instance is None:
            self._orchestrator_instance = CodeAssistOrchestrator(
                streaming_executor=self._streaming_executor,
                response_post_processor=self._response_post_processor,
                thought_signature_service=self._thought_signature_service,
                retry_policy=self._retry_policy,
                backend_type=getattr(self, "backend_type", "gemini"),
            )
        return self._orchestrator_instance

    @property
    def _chat_completion_coordinator_instance(self) -> IChatCompletionCoordinator:
        """Get or lazily create the chat completion coordinator."""
        if self._chat_completion_coordinator is None:
            self._chat_completion_coordinator = GeminiChatCompletionCoordinator(
                request_preparer=self._chat_preparer,
                orchestrator=self._orchestrator,
                token_refresher=self,  # Connector implements ITokenRefresher
                endpoint_config=self._endpoint_config,
                api_base_url=self.gemini_api_base_url or CODE_ASSIST_ENDPOINT,
                backend_type=getattr(self, "backend_type", "gemini"),
                vtc_wrapper_builder=self._vtc_wrapper_builder,
                error_mapper=self._error_mapper,
                thought_signature_service=self._thought_signature_service,
                key_name=getattr(self, "_key_name", None),
            )
        return self._chat_completion_coordinator

    def extract_retry_delay(self, error: BackendError) -> float | None:
        """Extract retry delay from error - implements IRetryDelayExtractor."""
        return self._extract_retry_delay(error)

    async def refresh_token_if_needed(self, *, force_reload: bool = False) -> bool:
        """Refresh token if needed - implements ITokenRefresher."""
        return await self._refresh_token_if_needed(force_reload=force_reload)

    # ==========================================================================
    # DEPRECATED: Backward-compatible properties for internal component access
    # ==========================================================================
    # These properties expose internal state from composed components (TokenManager,
    # FileWatcherState, GracefulDegradationManager) for backward compatibility.
    #
    # Access composed objects directly:
    # - self._token_manager for token operations
    # - self._file_watcher_state for file watching
    # - self._graceful_degradation for degradation logic
    # ==========================================================================

    def get_graceful_degradation_metrics(self) -> dict[str, float | int]:
        """Expose graceful degradation telemetry for diagnostics."""
        return self._graceful_degradation.get_metrics()

    def get_validation_errors(self) -> list[str]:
        """Get the current list of credential validation errors.

        Returns:
            List of validation error messages
        """
        return self._credential_validation_errors.copy()

    def _validate_credentials_structure(
        self, credentials: dict[str, Any], silent: bool = False
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials."""
        return CredentialLoader.validate_credentials_structure(credentials, silent)

    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that the OAuth credentials file exists and is readable."""
        is_valid, errors, _ = CredentialLoader.validate_credentials_file_exists(
            self.gemini_cli_oauth_path
        )
        return is_valid, errors

    def _validate_active_credentials_path(self) -> tuple[bool, list[str]]:
        """Validate the currently used credentials path, if known."""
        return CredentialLoader.validate_active_credentials_path(
            self._credentials_path, self.gemini_cli_oauth_path
        )

    def _fail_init(self, errors: list[str]) -> None:
        """Mark initialization as failed with given errors."""
        self._credential_validation_errors = errors
        self._initialization_failed = True
        self.is_functional = False

    def _degrade(self, errors: list[str]) -> None:
        """Degrade backend functionality due to credential issues."""
        self._credential_validation_errors = errors
        self.is_functional = False

    def _recover(self) -> None:
        """Recover backend functionality after credential issues are resolved."""
        self._credential_validation_errors = []
        self.is_functional = True
        self._initialization_failed = False

    def _handle_streaming_error(self, response: requests.Response) -> None:
        """Handle errors from streaming responses, checking for quota issues."""
        if response.status_code >= 400:
            try:
                error_detail = response.json()
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to parse streaming error response as JSON, using text fallback: %s",
                        e,
                        exc_info=True,
                    )
                error_detail = response.text

            error_message = ""
            if isinstance(error_detail, dict):
                error_message = error_detail.get("error", {}).get("message", "")

            # Handle Authentication Errors (401)
            if response.status_code == 401:
                logger.warning(
                    "Authentication failed for backend %s: %s",
                    self.name,
                    error_message,
                )
                raise AuthenticationError(
                    message=f"Code Assist API authentication failed: {error_message}",
                    details={"error": error_detail},
                )

            message_lower = error_message.lower()
            is_quota_error = (
                response.status_code == 429
                and isinstance(error_detail, dict)
                and (
                    "quota exceeded" in message_lower
                    or "resource exhausted" in message_lower
                    or "allowance" in message_lower
                )
            )

            if is_quota_error:
                # Set the quota exceeded flag, but keep backend functional for other models
                self._quota_exceeded = True
                logger.warning(
                    "Quota exhausted for backend %s: %s",
                    self.name,
                    error_message,
                )
                raise BackendError(
                    message=f"Gemini CLI OAuth quota exhausted: {error_detail}",
                    code="quota_exceeded",
                    status_code=response.status_code,
                )

            raise BackendError(
                message=f"Code Assist API streaming error: {error_detail}",
                code="code_assist_error",
                status_code=response.status_code,
            )

    def _mark_backend_unusable(self, *, reason: str = "quota_exceeded") -> None:
        """Mark this backend as unusable.

        For quota-style errors, we only set a flag but keep the backend functional
        so other models can still be used. The specific model should be put in cooldown
        instead of disabling the entire backend.

        Args:
            reason: The reason for marking the backend unusable. If "quota_exceeded",
                    only sets the quota flag but keeps backend functional.
        """
        self._quota_exceeded = True

        # For quota exhaustion, don't disable the entire backend - other models may work
        if reason == "quota_exceeded":
            logger.warning(
                "Backend %s has quota exhaustion for some models. "
                "Specific models will be in cooldown but backend remains functional.",
                self.name,
            )
            return

        # For non-quota errors (e.g., auth failures), disable the backend entirely
        self.is_functional = False
        logger.error(
            "Backend %s marked as unusable due to %s. "
            "Manual intervention may be required to restore functionality.",
            self.name,
            reason,
        )

    def _estimate_prompt_tokens(
        self, code_assist_request: dict[str, Any]
    ) -> int | None:
        """Best-effort estimate of prompt token usage for the current request.

        Uses the injected TiktokenEstimator service for SOLID compliance.
        """
        return self._token_estimator.estimate_prompt_tokens(code_assist_request)

    def _get_prompt_limit(self, effective_model: str) -> int | None:
        """Resolve the prompt-size threshold for the given model."""
        override_limit = getattr(self.config, "context_window_override", None)
        return get_prompt_limit(
            effective_model,
            self._prompt_limit_overrides,
            self._prompt_limit_prefix_overrides,
            default_limit=self._default_prompt_limit,
            context_window_override=override_limit,
        )

    def _enforce_prompt_limit(
        self,
        prompt_tokens: int | None,
        effective_model: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Prevent Code Assist requests that would exceed the plan allowance."""
        limit = self._get_prompt_limit(effective_model)
        enforce_prompt_limit(prompt_tokens, effective_model, limit, request_id)

    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        # Sync main_loop to state before starting
        self._file_watcher_state.main_loop = self._main_loop
        FileWatcher.start_file_watching(
            self._credentials_path,
            self._stop_file_watching,
            self._file_watcher_state,
            self._handle_credentials_file_change,
        )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file."""
        FileWatcher.stop_file_watching(self._file_watcher_state)

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload when the credentials file changes."""
        # Sync main_loop to state
        self._file_watcher_state.main_loop = self._main_loop
        FileWatcher.schedule_credentials_reload(
            self._file_watcher_state,
            self._handle_credentials_file_change,
            self._stop_file_watching,
        )

    async def _handle_credentials_file_change(self) -> None:
        """Handle credentials file change event.

        This method is called when the file system watcher detects a change to the
        oauth_creds.json file. Delegates to credential coordinator if available.
        """
        if self._credential_coordinator:
            # Delegate to coordinator's file change handler
            # Type narrowing: cast to concrete type to access private attributes
            from src.connectors.gemini_base.credential_coordinator import (
                GeminiCredentialCoordinator,
            )

            coordinator = self._credential_coordinator
            if isinstance(coordinator, GeminiCredentialCoordinator):
                await coordinator._handle_credentials_file_change()
                # Sync state for backward compatibility
                if coordinator.credentials:
                    self.__dict__["_oauth_credentials"] = (
                        coordinator.credentials.to_dict()
                    )
                    self._credentials_path = coordinator._credentials_path
                    self._credentials_fingerprint = coordinator._credentials_fingerprint
                    self._credentials_file_hash = coordinator._credentials_file_hash
                    self._last_credentials_event_hash = (
                        coordinator._last_credentials_event_hash
                    )
            # Update functional state based on coordinator state
            if self._credential_coordinator.credentials:
                self._recover()
            return

        # Fallback to old logic
        success = False
        try:
            previous_fingerprint = self._credentials_fingerprint

            # Validate file first (silently)
            ok, errs = self._validate_active_credentials_path()
            if not ok:
                self._degrade(errs)
                logger.warning(
                    f"Updated credentials file is invalid: {'; '.join(errs)}"
                )
                return

            # Attempt to reload silently first to check if credentials actually changed
            credentials_changed = False
            if await self._load_oauth_credentials(force_reload=True, silent=True):
                if (
                    previous_fingerprint is None
                    or previous_fingerprint != self._credentials_fingerprint
                ):
                    # Credentials actually changed
                    credentials_changed = True
                    logger.debug("Handling credentials file change...")
                    logger.info("Detected credential change; refreshing token...")

                # Always refresh token, even if credentials unchanged (token may be expired)
                refreshed = await self._refresh_token_if_needed()
                if refreshed:
                    self._recover()
                    if credentials_changed:
                        logger.info(
                            "Successfully reloaded credentials from updated file"
                        )
                    success = True
                else:
                    self._degrade(
                        ["Credentials refreshed from file but token remains invalid"]
                    )
                    logger.warning(
                        "Credentials file reload completed but token is still invalid"
                    )
            else:
                self._degrade(["Failed to reload credentials after file change"])
                logger.error("Failed to reload credentials after file change")

        except Exception as e:
            self._degrade([f"Error handling credentials file change: {e}"])
            logger.error(f"Error handling credentials file change: {e}", exc_info=True)
        finally:
            if success:
                self._last_credentials_event_hash = self._credentials_file_hash
            else:
                self._last_credentials_event_hash = None

    async def _validate_runtime_credentials(self) -> bool:
        """Validate credentials at runtime with throttling.

        Returns:
            bool: True if credentials are valid, False otherwise
        """
        now = time.time()
        if now - self._last_validation_time < 30:
            return self.is_backend_functional()
        self._last_validation_time = now

        # Delegate to credential coordinator
        if self._credential_coordinator:
            is_valid = await self._credential_coordinator.validate_runtime()
            if not is_valid:
                self._degrade(["Token expired and automatic refresh failed"])
                logger.warning(
                    "Token validation failed; automatic refresh did not produce a valid token."
                )
                return False
        else:
            # Fallback to old logic
            refreshed = await self._refresh_token_if_needed()
            if not refreshed:
                self._degrade(["Token expired and automatic refresh failed"])
                logger.warning(
                    "Token validation failed; automatic refresh did not produce a valid token."
                )
                return False

        if not self.is_backend_functional():
            self._recover()
        return True

    def _seconds_until_token_expiry(self) -> float | None:
        """Return seconds remaining before token expiry, or None if unknown."""
        return self._token_manager.seconds_until_token_expiry(self._oauth_credentials)

    def _is_token_expired(
        self, buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS
    ) -> bool:
        """Check if the current access token is expired or within buffer window."""
        return self._token_manager.is_token_expired(
            self._oauth_credentials, buffer_seconds
        )

    def _should_trigger_cli_refresh(self) -> bool:
        """Determine whether we should proactively trigger CLI token refresh."""
        return self._token_manager.should_trigger_cli_refresh(self._oauth_credentials)

    def _launch_cli_refresh_process(self) -> None:
        """Launch gemini CLI command to refresh the OAuth token in background."""
        self._token_manager.launch_cli_refresh_process()

    async def _poll_for_new_token(self, max_wait_seconds: float | None = None) -> bool:
        """Poll the credential file for an updated token after CLI refresh."""
        return await self._token_manager.poll_for_new_token(self, max_wait_seconds)

    def _get_refresh_token(self) -> str | None:
        """Get refresh token, either from credentials or cached value."""
        return self._token_manager.get_refresh_token(self._oauth_credentials)

    async def _refresh_token_if_needed(self, *, force_reload: bool = False) -> bool:
        """Ensure a valid access token is available, refreshing when necessary.

        Implements IConnectorContext interface by delegating to credential coordinator.
        """
        if self._credential_coordinator:
            return await self._credential_coordinator.refresh_if_needed(
                force_reload=force_reload
            )
        # Fallback to token manager for backward compatibility
        return await self._token_manager.refresh_token_if_needed(
            self, force_reload=force_reload
        )

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file."""
        await CredentialLoader.save_oauth_credentials(credentials)

    @staticmethod
    def _compute_credentials_fingerprint(credentials: dict[str, Any]) -> str:
        """Return a stable fingerprint for the currently loaded credentials."""
        return CredentialLoader.compute_credentials_fingerprint(credentials)

    async def _load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Load OAuth credentials from oauth_creds.json file."""
        return await CredentialLoader.load_oauth_credentials(self, force_reload, silent)  # type: ignore[arg-type]

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize backend with enhanced validation following the stale token handling pattern."""
        logger.info(
            "Initializing Gemini OAuth Personal backend with enhanced validation."
        )

        # Capture the current event loop for thread-safe operations
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            # If no running loop, create a new one
            self._main_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._main_loop)

        # Set the API base URL for Google Code Assist API (used by oauth-personal)
        self.gemini_api_base_url = kwargs.get(
            "gemini_api_base_url", "https://cloudcode-pa.googleapis.com"
        )

        # Set custom .gemini directory path (defaults to ~/.gemini)
        self.gemini_cli_oauth_path = kwargs.get("gemini_cli_oauth_path")

        # Delegate credential initialization to coordinator
        if self._credential_coordinator is None:
            self._fail_init(["Credential coordinator not initialized"])
            return

        try:
            await self._credential_coordinator.initialize(
                gemini_cli_oauth_path=self.gemini_cli_oauth_path
            )
            # Sync credentials to instance variable for backward compatibility
            if self._credential_coordinator.credentials:
                self.__dict__["_oauth_credentials"] = (
                    self._credential_coordinator.credentials.to_dict()
                )
                # Type narrowing: cast to concrete type to access private attributes
                from src.connectors.gemini_base.credential_coordinator import (
                    GeminiCredentialCoordinator,
                )

                coordinator = self._credential_coordinator
                if isinstance(coordinator, GeminiCredentialCoordinator):
                    self._credentials_path = coordinator._credentials_path
                    self._credentials_fingerprint = coordinator._credentials_fingerprint
                    self._credentials_file_hash = coordinator._credentials_file_hash
        except AuthenticationError as e:
            # Convert coordinator errors to initialization failures
            errors = [str(e.message)] if hasattr(e, "message") else [str(e)]
            if (
                hasattr(e, "details")
                and isinstance(e.details, dict)
                and "errors" in e.details
            ):
                errors = e.details["errors"]
            self._fail_init(errors)
            return

        # Check if token refresh succeeded
        refreshed = await self._credential_coordinator.refresh_if_needed()
        if not refreshed:
            pending_message = "OAuth token refresh pending; Gemini CLI background refresh was triggered."
            self._degrade([pending_message])
            self._initialization_failed = False
            self._last_validation_time = time.time()
            logger.warning(
                "Gemini OAuth Personal backend started with an expired token; "
                "waiting for the Gemini CLI to refresh credentials."
            )
            # File watching is started by coordinator, so we're done here
            return

        # Delegate model loading to model registry (non-fatal)
        if self._model_registry is not None:
            try:
                await self._model_registry.ensure_loaded()
                # Sync model state for backward compatibility
                # Check for attributes directly to support both real instances and mocks
                registry = self._model_registry
                if (
                    hasattr(registry, "_available_models")
                    and hasattr(registry, "_available_models_set")
                    and hasattr(registry, "_models_from_api")
                ):
                    # Access private attributes for backward compatibility with concrete implementations
                    self.available_models = getattr(registry, "_available_models", None)  # type: ignore[assignment,attr-defined]
                    self._available_models_set = getattr(registry, "_available_models_set", None)  # type: ignore[assignment,attr-defined]
                    self._models_from_api = getattr(registry, "_models_from_api", None)  # type: ignore[assignment,attr-defined]
            except Exception as e:
                logger.warning(
                    f"Failed to load models during initialization: {e}", exc_info=True
                )
                # Continue with initialization even if model loading fails

        # Mark functional
        self.is_functional = True
        self._last_validation_time = time.time()

        logger.info(
            f"Gemini OAuth Personal backend initialized successfully with {len(self.available_models) if self.available_models else 0} models."
        )

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached - OAuth version.

        Delegates to model registry for model discovery and caching.
        """
        if self._model_registry:
            await self._model_registry.ensure_loaded()
            # Sync model state for backward compatibility
            # Check for attributes directly to support both real instances and mocks
            registry = self._model_registry
            if (
                hasattr(registry, "_available_models")
                and hasattr(registry, "_available_models_set")
                and hasattr(registry, "_models_from_api")
            ):
                # Access private attributes for backward compatibility with concrete implementations
                self.available_models = getattr(registry, "_available_models", None)  # type: ignore[assignment,attr-defined]
                self._available_models_set = getattr(registry, "_available_models_set", None)  # type: ignore[assignment,attr-defined]
                self._models_from_api = getattr(registry, "_models_from_api", None)  # type: ignore[assignment,attr-defined]
        else:
            # Fallback to old logic
            if self.available_models:
                return

            if not self._oauth_credentials:
                return

            # Try to load models from the fetchAvailableModels API
            await self._load_models_from_api()

            # If API loading failed, fall back to hardcoded model list
            if not self.available_models:
                # Use a hardcoded list based on gemini-cli's tokenLimits.ts and models.ts
                self.available_models = [
                    # Current generation (2.5 series) - DEFAULT models
                    "gemini-2.5-pro",
                    "gemini-2.5-flash",
                    "gemini-2.5-flash-lite",
                    # Preview models
                    "gemini-2.5-pro-preview-05-06",
                    "gemini-2.5-pro-preview-06-05",
                    "gemini-2.5-flash-preview-05-20",
                    # 2.0 series
                    "gemini-2.0-flash",
                    "gemini-2.0-flash-thinking-exp-1219",
                    "gemini-2.0-flash-preview-image-generation",
                    # 1.5 series
                    "gemini-1.5-pro",
                    "gemini-1.5-flash",
                    # Embedding model
                    "gemini-embedding-001",
                ]
                # Build the set cache from the fallback list
                self._available_models_set = set(self.available_models)
                logger.info(
                    f"Loaded {len(self.available_models)} known Code Assist models (hardcoded fallback)"
                )

    def _get_api_headers(self) -> dict[str, str]:
        """
        Get headers for API requests (used with httpx client).

        Delegates to the endpoint config strategy for backend-specific headers.
        """
        return self._endpoint_config.get_api_headers(self._oauth_credentials)

    def _get_session_headers(self) -> dict[str, str]:
        """
        Get headers for AuthorizedSession requests (used with requests library).

        Delegates to the endpoint config strategy for backend-specific headers
        (e.g., custom User-Agent for Antigravity).
        """
        return self._endpoint_config.get_session_headers()

    async def _load_models_from_api(self) -> None:
        """
        Retrieve model slugs from the fetchAvailableModels endpoint.

        Uses the v1internal:fetchAvailableModels endpoint which returns a dictionary
        of available models. The models are extracted from the "models" dictionary keys
        in the response, which contains the exhaustive list of all supported models.

        This method is designed to work with both the standard Code Assist API
        (cloudcode-pa.googleapis.com) and sandbox variants (e.g., Antigravity).
        """
        if not await self._refresh_token_if_needed():
            return
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            return

        headers = self._get_api_headers()

        base_url = (self.gemini_api_base_url or CODE_ASSIST_ENDPOINT).rstrip("/")
        url = f"{base_url}/v1internal:fetchAvailableModels"

        try:
            response = await self.client.get(url, headers=headers, timeout=15.0)
        except Exception as exc:
            logger.warning(
                "Failed to reach fetchAvailableModels endpoint %s: %s", url, exc
            )
            return

        if response.status_code != 200:
            logger.debug(
                "fetchAvailableModels endpoint %s returned %s: %s",
                url,
                response.status_code,
                response.text[:200] if response.text else "",
            )
            return

        try:
            data = response.json()
        except Exception as exc:
            logger.warning(
                "Failed to decode fetchAvailableModels response from %s: %s", url, exc
            )
            return

        # Extract model IDs from "models" dictionary keys
        # This is the exhaustive list of all supported models
        slugs: set[str] = set()
        models_dict = data.get("models", {})
        if isinstance(models_dict, dict):
            for model_key in models_dict:
                if isinstance(model_key, str) and model_key.strip():
                    slugs.add(model_key.strip())

        if slugs:
            self.available_models = sorted(slugs)
            # Update the cached model set for fast validation lookups
            self._available_models_set = slugs
            # Mark that models were loaded from API (enables validation)
            self._models_from_api = True
            logger.info(
                "Loaded %d models from fetchAvailableModels endpoint",
                len(self.available_models),
            )

    def _get_available_models_set(self) -> set[str]:
        """
        Get the cached set of available models for fast lookups.

        Returns:
            set[str]: Set of available model names
        """
        if not self._available_models_set:
            self._available_models_set = set(self.available_models or [])
        return self._available_models_set

    def get_available_models(self) -> list[str]:
        """Return available models with vendor prefix for unified model routing.

        Returns:
            List of available model names with 'google/' vendor prefix.
            For example: ['google/gemini-2.5-pro', 'google/gemini-2.5-flash']
        """
        if self._model_registry:
            return self._model_registry.list_public_models()

        # Fallback to old logic
        # Create reverse mapping for exposure
        internal_to_public = {
            v: k for k, v in self._public_to_internal_model_map.items()
        }

        models = []
        for m in self.available_models or []:
            # Map internal name to public alias if exists
            public_name = internal_to_public.get(m, m)
            models.append(add_vendor_prefix(public_name, GOOGLE_VENDOR_PREFIX))

        return models

    def validate_model(self, model_name: str) -> None:
        """
        Validate that the requested model is available on this backend.

        Delegates to model registry for validation.

        Args:
            model_name: The model name to validate

        Raises:
            BackendError: If the model is not in the available models list
        """
        if self._model_registry:
            self._model_registry.validate(model_name)
            return

        # Fallback to old logic
        # Only validate if models were loaded from the API
        # Skip validation when using hardcoded fallback (may be outdated)
        if not getattr(self, "_models_from_api", False):
            logger.debug(
                "Model validation skipped - using hardcoded fallback model list"
            )
            return

        available_set = self._get_available_models_set()
        if not available_set:
            # Models not loaded yet or empty - skip validation
            logger.debug(
                "Model validation skipped - available models list not loaded yet"
            )
            return

        if model_name not in available_set:
            available_list = sorted(available_set)[:10]  # Show first 10 models
            suffix = (
                f"... and {len(available_set) - 10} more"
                if len(available_set) > 10
                else ""
            )
            raise BackendError(
                message=f"Model '{model_name}' is not available on this backend. "
                f"Available models: {', '.join(available_list)}{suffix}",
                code="model_not_found",
                status_code=400,
                backend_name=self.backend_type,
                details={
                    "requested_model": model_name,
                    "available_count": len(available_set),
                },
            )

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> ModelsListingResponse:
        """List available models using the fetchAvailableModels endpoint.

        Uses the v1internal:fetchAvailableModels endpoint and transforms the response
        to match the expected format. Ignores API key params since this uses OAuth.
        """
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401, detail="No OAuth access token available"
            )

        headers = self._get_api_headers()
        base_url = (self.gemini_api_base_url or CODE_ASSIST_ENDPOINT).rstrip("/")
        url = f"{base_url}/v1internal:fetchAvailableModels"

        try:
            response = await self.client.get(url, headers=headers, timeout=15.0)
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Failed to parse model fetch error response as JSON, using text fallback: %s",
                            e,
                            exc_info=True,
                        )
                    error_detail = response.text
                raise BackendError(
                    message=str(error_detail),
                    code="gemini_oauth_error",
                    status_code=response.status_code,
                    backend_name=self.backend_type,
                )

            data = response.json()

            # Transform the response to match expected format
            # Extract models from the response
            model_infos = []
            models_dict = data.get("models", {})
            if isinstance(models_dict, dict):
                for model_id, model_info in models_dict.items():
                    model_entry = ModelInfo(
                        id=f"models/{model_id}",
                        name=model_id,
                        object="model",
                        owned_by="google",
                    )
                    if isinstance(model_info, dict) and "displayName" in model_info:
                        model_entry.name = model_info["displayName"]

                    model_infos.append(model_entry)

            return ModelsListingResponse(object="list", data=model_infos)

        except httpx.TimeoutException as e:
            logger.error("Timeout connecting to Gemini OAuth API: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Timeout connecting to Gemini OAuth API ({e})"
            ) from e
        except httpx.RequestError as e:
            logger.error(
                "Request error connecting to Gemini OAuth API: %s", e, exc_info=True
            )
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini OAuth API ({e})"
            ) from e

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        *,
        openrouter_headers_provider: Callable[[Any, str], dict[str, str]] | None = None,
        key_name: str | None = None,
        **kwargs: Any,
    ) -> GeminiApiConfig:
        """Override to use access_token from OAuth credentials instead of API key."""
        # Use the OAuth access token for authentication
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401,
                detail="No valid Gemini OAuth access token available. Please authenticate.",
            )

        # Prefer explicit params, then kwargs, then instance attributes
        base = (
            gemini_api_base_url
            or openrouter_api_base_url
            or kwargs.get("gemini_api_base_url")
            or getattr(self, "gemini_api_base_url", None)
        )

        if not base:
            raise HTTPException(
                status_code=500, detail="Gemini API base URL must be provided."
            )

        # Use OAuth access token instead of API key (reload if expired)
        # Ensure token is fresh enough
        await self._refresh_token_if_needed()
        access_token = (
            self._oauth_credentials.get("access_token")
            if self._oauth_credentials
            else None
        )
        if not access_token:
            raise HTTPException(
                status_code=401, detail="Missing access_token after refresh."
            )

        return GeminiApiConfig(
            base_url=base.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

    async def _perform_health_check(self) -> bool:
        """Perform a health check by testing API connectivity.

        This method tests actual API connectivity by making a simple request to verify
        the OAuth token works and the service is accessible.

        Uses the fetchAvailableModels endpoint which is supported by all Code Assist API
        variants (standard and sandbox).

        Returns:
            bool: True if health check passes, False otherwise
        """
        try:
            # Ensure token is refreshed before testing
            if not await self._refresh_token_if_needed():
                logger.warning("Health check failed - couldn't refresh OAuth token")
                return False

            # Test API connectivity with a simple GET request
            if not self._oauth_credentials or not self._oauth_credentials.get(
                "access_token"
            ):
                logger.warning("Health check failed - no access token available")
                return False

            base_url = (self.gemini_api_base_url or CODE_ASSIST_ENDPOINT).rstrip("/")
            headers = self._get_api_headers()

            # Use fetchAvailableModels endpoint for health check
            # This endpoint is supported by all Code Assist API variants
            fetch_models_url = f"{base_url}/v1internal:fetchAvailableModels"
            try:
                response = await self.client.get(
                    fetch_models_url, headers=headers, timeout=10.0
                )
            except httpx.TimeoutException as te:
                logger.error(
                    f"Health check timeout calling {fetch_models_url}: {te}",
                    exc_info=True,
                )
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {fetch_models_url}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info(
                    "Health check passed - API connectivity verified via fetchAvailableModels"
                )
                self._health_checked = True
                return True

            # Fallback: use loadCodeAssist which is reliable on Code Assist API
            load_url = f"{base_url}/v1internal:loadCodeAssist"
            payload = {
                "metadata": {
                    "ideType": "IDE_UNSPECIFIED",
                    "platform": "PLATFORM_UNSPECIFIED",
                    "pluginType": "GEMINI",
                }
            }
            try:
                response = await self.client.post(
                    load_url, headers=headers, json=payload, timeout=10.0
                )
            except httpx.TimeoutException as te:
                logger.error(
                    f"Health check timeout calling {load_url}: {te}", exc_info=True
                )
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {load_url}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info("Health check passed via loadCodeAssist")
                self._health_checked = True
                return True
            logger.warning(
                f"Health check failed - API returned status {response.status_code}"
            )
            return False

        except AuthenticationError as e:
            logger.error(
                f"Health check failed - authentication error: {e}", exc_info=True
            )
            return False
        except BackendError as e:
            logger.error(f"Health check failed - backend error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Health check failed - unexpected error: {e}", exc_info=True)
            return False

    async def _ensure_healthy(self) -> None:
        """Ensure the backend is healthy before use.

        Delegates to health check service for first-use health checks.
        """
        if self._health_check_service:
            await self._health_check_service.ensure_healthy()
            # Sync health checked state for backward compatibility
            self._health_checked = True
            return

        # Fallback to old logic
        if not hasattr(self, "_health_checked") or not self._health_checked:
            logger.info(
                "Performing first-use health check for Gemini OAuth Personal backend"
            )

            # Refresh token if needed before health check
            refreshed = await self._refresh_token_if_needed()
            if not refreshed:
                raise BackendError("Failed to refresh OAuth token during health check")

            # Perform health check (non-blocking - we only fail on token issues)
            healthy = await self._perform_health_check()
            if not healthy:
                logger.warning(
                    "Health check did not pass, but continuing with valid OAuth credentials. "
                    "The backend will be tested when the first real request is made."
                )
            # Mark as checked regardless - we have valid credentials
            self._health_checked = True
            logger.info("Backend health check completed - ready for use")

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Any = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        """Handle chat completions using Google Code Assist API.

        This method delegates to the chat completion coordinator for orchestration.
        """
        # Runtime validation with descriptive errors
        if not await self._validate_runtime_credentials():
            details = (
                "; ".join(self._credential_validation_errors)
                or "Backend is not functional"
            )
            raise HTTPException(
                status_code=502,
                detail=f"No valid credentials found for backend {self.name}: {details}",
            )

        if not await self._refresh_token_if_needed():
            raise HTTPException(
                status_code=502,
                detail=f"No valid credentials found for backend {self.name}: Failed to refresh expired token",
            )

        # Perform health check on first use (includes token refresh)
        await self._ensure_healthy()

        try:
            # Use the effective model (strip backend and vendor prefixes if present)
            model_name = effective_model

            # Strip backend prefix (e.g., "gemini-oauth-plan:")
            prefix = "gemini-oauth-plan:"
            if model_name.startswith(prefix):
                model_name = model_name[len(prefix) :]

            # Strip vendor prefix (e.g., "google/") for unified model naming
            model_name = strip_vendor_prefix(model_name, GOOGLE_VENDOR_PREFIX)

            # Map public alias to internal model name if exists
            if self._model_registry:
                model_name = self._model_registry.to_internal_name(model_name)
            else:
                model_name = self._public_to_internal_model_map.get(
                    model_name, model_name
                )

            # Convert processed_messages to ChatMessage list for coordinator
            chat_messages: list[ChatMessage] = []
            for msg in processed_messages:
                if isinstance(msg, dict):
                    chat_messages.append(
                        ChatMessage(
                            role=msg.get("role", "user"),
                            content=msg.get("content", ""),
                        )
                    )
                elif isinstance(msg, ChatMessage):
                    chat_messages.append(msg)

            # Delegate to chat completion coordinator
            response = await self._chat_completion_coordinator_instance.execute(
                request_data=request_data,
                processed_messages=chat_messages,
                effective_model=model_name,
            )

            return response

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except AuthenticationError:
            # Re-raise authentication errors
            raise
        except BackendError:
            # Re-raise backend errors
            raise
        except InvalidRequestError:
            # Let context window overflows bubble up for clients to handle
            raise
        except Exception as e:
            # Normalize exceptions via error mapper if available
            if self._error_mapper:
                try:
                    mapped_error = self._error_mapper.map_exception(
                        e, backend_name=getattr(self, "backend_type", "gemini")
                    )
                    # map_exception returns LLMProxyError (or raises HTTPException)
                    raise mapped_error from e
                except Exception as mapped_exc:
                    # If map_exception raised HTTPException, re-raise it
                    # (HTTPException must be raised, not returned, for FastAPI)
                    raise mapped_exc from e
            # Fallback: convert to BackendError
            logger.error(
                f"Error in Gemini OAuth Personal chat_completions: {e}",
                exc_info=True,
            )
            raise BackendError(
                message=f"Gemini OAuth Personal chat completion failed: {e!s}"
            ) from e

    def _build_code_assist_request_body(
        self,
        effective_model: str,
        project_id: str,
        request_data: Any,
        code_assist_request: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the outer request body wrapper for Code Assist API.

        This method delegates to the injected request body builder strategy,
        allowing different backends to customize the request format.

        Args:
            effective_model: The model name to use
            project_id: The project ID from loadCodeAssist
            request_data: The original request data (for generating user_prompt_id)
            code_assist_request: The inner request with contents, generationConfig, etc.

        Returns:
            Complete request body dict ready to send to the API
        """
        return self._request_body_builder.build(
            effective_model=effective_model,
            project_id=project_id,
            request_data=request_data,
            inner_request=code_assist_request,
            user_prompt_id_generator=self._generate_user_prompt_id,
        )

    async def _accumulate_streaming_response(
        self, streaming_response: StreamingResponseEnvelope
    ) -> ResponseEnvelope:
        """Backward-compatible accumulator helper for tests and callers."""
        accumulator = StreamingResponseAccumulator(
            backend_type=getattr(self, "backend_type", "gemini")
        )
        return await accumulator.accumulate(streaming_response)

    @staticmethod
    def _sanitize_code_assist_tools(
        canonical_request: Any, code_assist_request: dict[str, Any]
    ) -> None:
        """Ensure only Gemini-compatible function tools are sent."""
        sanitize_code_assist_tools(canonical_request, code_assist_request)

    async def _attempt_auth_refresh_with_policy(
        self,
        error: Exception,
        *,
        is_streaming: bool,
        has_attempted: bool,
    ) -> bool:
        """Apply auth refresh policy and perform the refresh if allowed."""
        policy = cast(
            IAuthRefreshPolicy | None, getattr(self, "_auth_refresh_policy", None)
        )
        if policy is None:
            return False

        attempt = 1 if has_attempted else 0
        try:
            decision = policy.should_refresh(error, attempt, is_streaming=is_streaming)
        except Exception as policy_error:  # pragma: no cover - defensive
            logger.warning(
                "Auth refresh policy evaluation failed: %s",
                policy_error,
                exc_info=True,
            )
            return False

        if not decision.should_refresh:
            return False

        AUTH_RETRY_TIMEOUT = decision.timeout_seconds or 30.0
        logger.info(
            "Received 401 Unauthorized; applying auth refresh policy (attempt=%s, timeout=%.1fs, streaming=%s)",
            attempt + 1,
            AUTH_RETRY_TIMEOUT,
            is_streaming,
        )

        try:
            refreshed = await asyncio.wait_for(
                self._refresh_token_if_needed(force_reload=decision.force_reload),
                timeout=AUTH_RETRY_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Token refresh timed out after %.1fs; will propagate auth error",
                AUTH_RETRY_TIMEOUT,
            )
            return False
        except Exception as refresh_error:
            logger.error(
                "Error during token refresh attempt: %s",
                refresh_error,
                exc_info=True,
            )
            return False

        if refreshed:
            logger.info(
                "Token refresh successful (attempt=%s, streaming=%s); retrying request",
                attempt + 1,
                is_streaming,
            )
            return True

        logger.warning(
            "Token refresh failed after policy refresh attempt; propagating auth error"
        )
        return False

    async def _chat_completions_code_assist(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _in_graceful_degradation: bool = False,
        _auth_retry_attempted: bool = False,
        _rate_limit_retry_attempted: bool = False,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions using the Code Assist API.

        This method delegates to the chat completion coordinator for orchestration,
        while preserving auth retry wrapper logic for backward compatibility.

        **Note**: This method is for non-streaming requests. The coordinator determines
        streaming vs non-streaming based on `request_data.stream`, so we ensure it's False.
        """
        # Ensure request_data.stream is False for non-streaming requests
        # Coordinator determines streaming based on this flag, so we must set it correctly
        if hasattr(request_data, "model_copy") and callable(request_data.model_copy):
            # Pydantic model - create a modified copy
            request_data = request_data.model_copy(update={"stream": False})
        elif isinstance(request_data, dict):
            # Dict - modify directly
            request_data = {**request_data, "stream": False}
        elif hasattr(request_data, "stream"):
            # Object with stream attribute - validate it's False
            current_stream = getattr(request_data, "stream", False)
            if current_stream:
                logger.warning(
                    "_chat_completions_code_assist called with stream=True, "
                    "forcing stream=False to match method intent"
                )
                # Try to set it if possible
                try:
                    request_data.stream = False
                except (AttributeError, TypeError):
                    # If immutable, create a copy if possible
                    if hasattr(request_data, "model_copy"):
                        request_data = request_data.model_copy(update={"stream": False})
                    elif hasattr(request_data, "__dict__"):
                        # Create a shallow copy and modify
                        import copy

                        request_data = copy.copy(request_data)
                        request_data.stream = False

        # Convert processed_messages to ChatMessage list for coordinator
        chat_messages: list[ChatMessage] = []
        for msg in processed_messages:
            if isinstance(msg, dict):
                chat_messages.append(
                    ChatMessage(
                        role=msg.get("role", "user"),
                        content=msg.get("content", ""),
                    )
                )
            elif isinstance(msg, ChatMessage):
                chat_messages.append(msg)

        try:
            # Delegate to chat completion coordinator
            # Coordinator will check request_data.stream (now guaranteed to be False)
            response = await self._chat_completion_coordinator_instance.execute(
                request_data=request_data,
                processed_messages=chat_messages,
                effective_model=effective_model,
            )

            # Validate return type matches method intent (non-streaming should return ResponseEnvelope)
            if isinstance(response, StreamingResponseEnvelope):
                logger.warning(
                    "Coordinator returned StreamingResponseEnvelope for non-streaming request. "
                    "This may indicate a bug in coordinator or request_data.stream was not set correctly."
                )

            return response

        except AuthenticationError as e:
            # Coordinator delegates to orchestrator -> StreamingExecutor, which handles
            # auth retries internally. If that fails, AuthenticationError bubbles up here.
            # This connector-level retry is a fallback for cases where StreamingExecutor's
            # retry didn't succeed (e.g., token refresh failed or retry policy denied retry).
            should_retry = await self._attempt_auth_refresh_with_policy(
                e,
                is_streaming=False,
                has_attempted=_auth_retry_attempted,
            )
            if should_retry:
                return await self._chat_completions_code_assist(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=effective_model,
                    _in_graceful_degradation=_in_graceful_degradation,
                    _auth_retry_attempted=True,
                    _rate_limit_retry_attempted=_rate_limit_retry_attempted,
                    **kwargs,
                )
            logger.error(f"Authentication error during API call: {e}", exc_info=True)
            raise
        except BackendError as e:
            if e.status_code == 401 and await self._attempt_auth_refresh_with_policy(
                e,
                is_streaming=False,
                has_attempted=_auth_retry_attempted,
            ):
                return await self._chat_completions_code_assist(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=effective_model,
                    _in_graceful_degradation=_in_graceful_degradation,
                    _auth_retry_attempted=True,
                    **kwargs,
                )

            if self._is_rate_limit_like_error(e):
                logger.info("Backend rate limited during API call: %s", e)
            else:
                logger.error(
                    "Backend error during API call: %s (status=%s, code=%s)",
                    e,
                    getattr(e, "status_code", None),
                    getattr(e, "code", None),
                )
            raise
        except InvalidRequestError as e:
            logger.warning("Request blocked locally: %s", e, exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error during API call: {e}", exc_info=True)
            raise BackendError(f"Unexpected error during API call: {e}") from e

    async def _chat_completions_code_assist_streaming(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _rate_limit_retry_attempted: bool = False,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions using the Code Assist API.

        This method delegates to the chat completion coordinator for orchestration,
        while preserving streaming error handling (auth error stream generation).

        **Note**: This method is for streaming requests. The coordinator determines
        streaming vs non-streaming based on `request_data.stream`, so we ensure it's True.
        """
        from src.core.ports.streaming_contracts import handle_streaming_error

        # Ensure request_data.stream is True for streaming requests
        # Coordinator determines streaming based on this flag, so we must set it correctly
        if hasattr(request_data, "model_copy") and callable(request_data.model_copy):
            # Pydantic model - create a modified copy
            request_data = request_data.model_copy(update={"stream": True})
        elif isinstance(request_data, dict):
            # Dict - modify directly
            request_data = {**request_data, "stream": True}
        elif hasattr(request_data, "stream"):
            # Object with stream attribute - validate it's True
            current_stream = getattr(request_data, "stream", False)
            if not current_stream:
                logger.warning(
                    "_chat_completions_code_assist_streaming called with stream=False, "
                    "forcing stream=True to match method intent"
                )
                # Try to set it if possible
                try:
                    request_data.stream = True
                except (AttributeError, TypeError):
                    # If immutable, create a copy if possible
                    if hasattr(request_data, "model_copy"):
                        request_data = request_data.model_copy(update={"stream": True})
                    elif hasattr(request_data, "__dict__"):
                        # Create a shallow copy and modify
                        import copy

                        request_data = copy.copy(request_data)
                        request_data.stream = True

        # Convert processed_messages to ChatMessage list for coordinator
        chat_messages: list[ChatMessage] = []
        for msg in processed_messages:
            if isinstance(msg, dict):
                chat_messages.append(
                    ChatMessage(
                        role=msg.get("role", "user"),
                        content=msg.get("content", ""),
                    )
                )
            elif isinstance(msg, ChatMessage):
                chat_messages.append(msg)

        try:
            # Delegate to chat completion coordinator
            # Coordinator will check request_data.stream (now guaranteed to be True)
            response = await self._chat_completion_coordinator_instance.execute(
                request_data=request_data,
                processed_messages=chat_messages,
                effective_model=effective_model,
            )

            # Validate return type matches method intent (streaming should return StreamingResponseEnvelope)
            if not isinstance(response, StreamingResponseEnvelope):
                # This shouldn't happen for streaming requests, but handle gracefully
                logger.warning(
                    "Coordinator returned non-streaming response for streaming request. "
                    "Converting to streaming format."
                )
                # Convert non-streaming response to streaming chunk
                from src.connectors.gemini_base.response_accumulator import (
                    response_envelope_to_stream_chunk,
                )

                async def single_chunk_stream() -> (
                    AsyncGenerator[ProcessedResponse, None]
                ):
                    chunk = response_envelope_to_stream_chunk(
                        response,
                        effective_model,
                        getattr(self, "backend_type", "gemini"),
                    )
                    yield chunk

                return StreamingResponseEnvelope(
                    content=single_chunk_stream(),
                    media_type="text/event-stream",
                    headers={},
                )

            return response

        except AuthenticationError as e:
            logger.error(
                f"Authentication error during streaming API call: {e}",
                exc_info=True,
            )
            error = e

            # Return SSE error stream instead of raising to prevent empty responses
            async def auth_error_stream() -> AsyncGenerator[ProcessedResponse, None]:
                chunk = await handle_streaming_error(
                    error,
                    getattr(request_data, "session_id", None),
                    effective_model,
                )
                error_payload = {
                    "choices": [{"delta": {}, "finish_reason": "error", "index": 0}],
                    "error": chunk.metadata.get("error"),
                }
                yield ProcessedResponse(content=error_payload)

            return StreamingResponseEnvelope(
                content=auth_error_stream(),
                media_type="text/event-stream",
                headers={},
            )
        except BackendError as e:
            if self._is_rate_limit_like_error(e):
                logger.info(
                    "Backend rate limited during streaming API call (no retry-after): %s",
                    e,
                )
            else:
                logger.error(
                    "Backend error during streaming API call: %s (status=%s, code=%s)",
                    e,
                    getattr(e, "status_code", None),
                    getattr(e, "code", None),
                )
            raise
        except InvalidRequestError as e:
            logger.warning("Streaming request blocked locally: %s", e, exc_info=True)
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during streaming API call: {e}", exc_info=True
            )
            raise BackendError(
                f"Unexpected error during streaming API call: {e}"
            ) from e

    def _build_vtc_wrapper(
        self, request_data: Any, effective_model: str
    ) -> StreamWrapper | None:
        """Build VTC wrapper for streaming responses if enabled.

        Delegates to VTC wrapper builder service.
        """
        if self._vtc_wrapper_builder:
            return self._vtc_wrapper_builder.build(
                request_data=request_data,
                effective_model=effective_model,
            )

        # Fallback to old logic for backward compatibility
        vtc_enabled = getattr(request_data, "vtc_enabled", False) or False
        if not vtc_enabled:
            return None

        tool_call_reactor = None
        arguments_parser = None
        arguments_fixup_pipeline = None
        try:
            from src.core.di.services import get_service_provider
            from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
                IToolArgumentsFixupPipeline,
            )
            from src.core.interfaces.tool_arguments_parser_interface import (
                IToolArgumentsParser,
            )
            from src.core.services.tool_call_reactor_service import (
                ToolCallReactorService,
            )

            provider = get_service_provider()
            tool_call_reactor = provider.get_service(ToolCallReactorService)
            arguments_parser = provider.get_service(IToolArgumentsParser)  # type: ignore[type-abstract]
            arguments_fixup_pipeline = provider.get_service(IToolArgumentsFixupPipeline)  # type: ignore[type-abstract]
        except Exception as exc:
            logger.warning("Failed to get tool call reactor services for VTC: %s", exc)

        reactor_context = {
            "backend_name": self.backend_type,
            "model_name": effective_model,
            "calling_agent": getattr(request_data, "agent", None),
            "client_os": getattr(request_data, "client_os", None),
        }
        session_id = getattr(request_data, "session_id", None)

        from src.core.services.streaming.vtc_response_wrapper import (
            wrap_processed_response_stream_with_vtc,
        )

        def wrapper(
            generator: AsyncIterator[ProcessedResponse],
        ) -> AsyncIterator[ProcessedResponse]:
            return wrap_processed_response_stream_with_vtc(
                generator,
                vtc_enabled=vtc_enabled,
                tool_call_reactor=tool_call_reactor,
                arguments_parser=arguments_parser,
                arguments_fixup_pipeline=arguments_fixup_pipeline,
                session_id=session_id,
                context=reactor_context,
            )

        return cast(StreamWrapper, wrapper)

    def _build_thought_signature_callback(
        self,
    ) -> Callable[[list[dict[str, Any]], str | None], None]:
        """Create a thought-signature storage callback for streaming executor."""

        def callback(tool_calls: list[dict[str, Any]], session_id: str | None) -> None:
            if self._thought_signature_service is not None:
                self._thought_signature_service.store_signatures_from_tool_calls(
                    tool_calls,
                    session_id,
                )

        return callback

    def _response_envelope_to_stream_chunk(
        self, response: ResponseEnvelope, model: str
    ) -> ProcessedResponse:
        """Convert a non-streaming response into a single streaming chunk.

        Delegates to response_envelope_to_stream_chunk module function.
        """
        return response_envelope_to_stream_chunk(
            response, model, getattr(self, "backend_type", "gemini")
        )

    def _generate_user_prompt_id(self, request_data: Any) -> str:
        """Generate a unique user_prompt_id for Code Assist requests.

        Delegates to user_prompt_id_generator module.
        """
        return _generate_user_prompt_id_impl(request_data)

    def _convert_to_code_assist_format(
        self, request_data: Any, processed_messages: list[Any], model: str
    ) -> dict[str, Any]:
        """Convert OpenAI-style request to Code Assist API format.

        **Note**: This method is preserved for backward compatibility but is no longer
        used internally. The coordinator handles request format conversion via
        ChatRequestPreparer and IMessageConverter interfaces. This method may be
        removed in a future refactoring if no external callers depend on it.
        """
        # Extract the last user message for generation
        user_message = ""
        for msg in reversed(processed_messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        if not user_message:
            # Fallback to first message if no user message found
            user_message = (
                processed_messages[0].get("content", "") if processed_messages else ""
            )

        # Build system prompt from conversation history
        system_prompt = ""
        conversation_context = []

        for msg in processed_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            elif role in ("user", "assistant"):
                # Avoid double-prefixing if the content already starts with a role label
                normalized = content.lstrip()
                lowered = normalized.lower()
                if lowered.startswith(("assistant:", "user:")):
                    normalized = normalized.split(":", 1)[1].lstrip()
                prefix = "Assistant" if role == "assistant" else "User"
                conversation_context.append(f"{prefix}: {normalized}")

        # Combine system prompt with conversation context
        # Build full_prompt efficiently using join to avoid O(n) string concatenations
        parts = []
        if system_prompt:
            parts.append(system_prompt)
        if conversation_context:
            parts.append("\n".join(conversation_context))
        full_prompt = "\n\n".join(parts) if parts else ""

        # Create Code Assist request format (matching Gemini CLI format)
        code_assist_request = {
            "model": model,
            "contents": [
                {"role": "user", "parts": [{"text": full_prompt or user_message}]}
            ],
            "generationConfig": self._build_generation_config(request_data),
        }

        return code_assist_request

    def _build_generation_config(self, request_data: Any) -> dict[str, Any]:
        """Build Code Assist generationConfig from request_data using Pydantic models.

        Delegates to GenerationConfigBuilder for implementation.

        **Note**: This method is preserved for backward compatibility. It's called by
        `_convert_to_code_assist_format` (which is also legacy). The coordinator handles
        generation config building via ChatRequestPreparer and GenerationConfigBuilder.
        This method may be removed in a future refactoring if no external callers depend on it.
        """
        builder = GenerationConfigBuilder()
        return builder.build(request_data)

    def _convert_from_code_assist_format(
        self, code_assist_response: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert Code Assist API response to OpenAI-compatible format.

        Delegates to convert_from_code_assist_format module function.

        **Note**: This method is preserved for backward compatibility but is no longer
        used internally. The coordinator handles response format conversion via
        orchestrator and response processors. This method may be removed in a future
        refactoring if no external callers depend on it.
        """
        return convert_from_code_assist_format(code_assist_response, model)

    def _is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown.

        Delegates to GracefulDegradationManager.
        """
        return self._graceful_degradation.is_in_cooldown(model)

    def _extract_retry_delay(self, error: BackendError) -> float | None:
        """Extract retry delay from error details.

        Delegates to retry_delay_parser module.
        """
        return _extract_retry_delay_impl(error)

    def _parse_retry_from_message(self, message: str) -> float | None:
        """Parse retry delay from natural language message.

        Delegates to retry_delay_parser module.
        """
        return _parse_retry_from_message_impl(message)

    @staticmethod
    def _parse_duration_string(duration: str) -> float | None:
        """Parse duration string like '10s' or '4h51m33.9s'.

        Delegates to retry_delay_parser module.
        """
        return _parse_duration_string_impl(duration)

    def _set_cooldown(self, model: str, duration: float | None = None) -> None:
        """Put a model into cooldown state.

        Args:
            model: The model to put in cooldown
            duration: Optional custom duration in seconds. If None, uses default config.

        Delegates to GracefulDegradationManager.
        """
        if duration is not None:
            # Custom duration - use module function with manager's state
            set_model_cooldown(
                model, self._graceful_degradation.model_retry_states, duration
            )
        else:
            # Default duration - use manager method
            self._graceful_degradation.set_cooldown(model)

    def _is_rate_limit_like_error(self, error: BackendError) -> bool:
        """Determine whether an error should trigger graceful degradation retries.

        Delegates to GracefulDegradationManager.
        """
        return self._graceful_degradation.is_rate_limit_like_error(error)

    async def _probe_model_recovery(
        self, model: str, bypass_interval_check: bool = False
    ) -> bool:
        """Probe if a model has recovered from cooldown.

        Args:
            model: The model to probe
            bypass_interval_check: If True, bypass the interval check (for testing)

        Returns:
            True if model has recovered, False otherwise
        """
        if not self._graceful_degradation.config.enable_recovery_probing:
            return False

        state = self._graceful_degradation.model_retry_states.get(model)
        if not state or not self._is_in_cooldown(model):
            return True

        # Check if enough time has passed since last probe
        now = time.time()
        if (
            not bypass_interval_check
            and now - state.last_probe_attempt
            < self._graceful_degradation.config.recovery_probe_interval
        ):
            return False

        state.last_probe_attempt = now

        try:
            # Make a simple test request to check if model is working
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Probing recovery for model %s", model)

            # Create a minimal test request
            test_request = CanonicalChatRequest(
                model=model,
                messages=[ChatMessage(role="user", content="recovery probe")],
                stream=False,
                max_tokens=10,
                temperature=0.1,
            )

            # Try the API call
            await self._chat_completions_code_assist(
                request_data=test_request,
                processed_messages=[{"role": "user", "content": "recovery probe"}],
                effective_model=model,
                _in_graceful_degradation=True,
            )

            # If we get here, the probe succeeded
            state.probe_success_count += 1

            # Need 2 successful probes to recover
            if state.probe_success_count >= 2:
                state.cooldown_until = (
                    time.time() - 1
                )  # Clear cooldown (set to past time)
                state.attempts = 0
                state.probe_success_count = 0
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Model %s recovered from cooldown", model)
                return True

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Model %s probe %d/2 succeeded",
                    model,
                    state.probe_success_count,
                )

        except AuthenticationError as auth_err:
            state.probe_success_count = 0
            # Auth errors are likely permanent until manual intervention or file update
            logger.warning(
                "Model %s recovery probe failed due to authentication error: %s. "
                "Checking credentials...",
                model,
                auth_err,
            )
            # Trigger a credential check/reload if possible
            task = asyncio.create_task(self._handle_credentials_file_change())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except BackendError as error:
            state.probe_success_count = 0
            log_message = (
                f"Model {model} recovery probe failed with backend error: {error}"
            )
            if self._is_rate_limit_like_error(error):
                logger.info(log_message)
            else:
                logger.warning(log_message)
        except Exception as exc:  # pragma: no cover - defensive logging path
            state.probe_success_count = 0
            logger.warning(
                "Model %s recovery probe encountered unexpected error: %s",
                model,
                exc,
            )

        return False

    async def _handle_429_with_graceful_degradation(
        self,
        original_model: str,
        request_data: Any,
        processed_messages: list[Any],
        error: BackendError | None = None,
        _in_graceful_degradation: bool = False,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Propagate 429s to the Resilience Layer; no connector-level retries/fallbacks."""
        if _in_graceful_degradation:
            raise BackendError(
                message="Recursive graceful degradation detected",
                code="recursive_graceful_degradation",
                status_code=429,
            )

        retry_after = self._extract_retry_delay(error) if error else None
        details: dict[str, Any] = {}
        if error and error.details:
            details = (
                dict(error.details)
                if isinstance(error.details, dict)
                else {"raw": error.details}
            )
        if retry_after is not None:
            details["retry_after"] = retry_after

        raise BackendError(
            message=(error.message if error else "Rate limit exceeded"),
            code=(error.code if error else "rate_limit_exceeded"),
            status_code=getattr(error, "status_code", 429) if error else 429,
            details=details or None,
            backend_name=self.backend_type,
        )

    async def _recovery_probing_loop(self) -> None:
        """Background task to probe for model recovery."""
        if not self._graceful_degradation.config.enable_recovery_probing:
            return

        sleep_fn = getattr(asyncio, "sleep", None)
        # When asyncio.sleep is monkeypatched (e.g., AsyncMock in tests), avoid
        # spinning a tight loop that starves the event loop.
        if sleep_fn and getattr(sleep_fn, "__module__", "") == "unittest.mock":
            return

        while True:
            try:
                await asyncio.sleep(
                    self._graceful_degradation.config.recovery_probe_interval
                )

                # Check each model in cooldown
                models_in_cooldown = [
                    model
                    for model in self._graceful_degradation.model_retry_states
                    if self._is_in_cooldown(model)
                ]

                for model in models_in_cooldown:
                    await self._probe_model_recovery(model)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Error in recovery probing loop: %s",
                        e,
                    )

    @abc.abstractmethod
    async def _discover_project_id(self, auth_session) -> str:
        """Discover or retrieve the project ID for Code Assist API."""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Shutdown the connector and clean up resources.

        This method is called by BackendLifecycleManager during backend shutdown
        to ensure proper cleanup of resources like TokenManager subprocesses.
        """
        # Clean up TokenManager subprocess if available
        if hasattr(self, "_token_manager") and self._token_manager:
            try:
                await self._token_manager.cleanup()
            except asyncio.CancelledError:
                # Re-raise cancellation to allow proper cleanup
                raise
            except (
                OSError,
                ProcessLookupError,
                AttributeError,
                RuntimeError,
                ValueError,
            ) as exc:
                # Best-effort cleanup; suppress errors to avoid masking real failures
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Error cleaning up TokenManager during shutdown: %s",
                        exc,
                        exc_info=True,
                    )

    def __del__(self):
        """Cleanup file watcher on destruction."""
        # Guard against partial initialization
        if hasattr(self, "_file_watcher_state"):
            self._stop_file_watching()

        # Cleanup CLI refresh process via token manager
        # Note: This is best-effort cleanup in __del__. The preferred path
        # is via shutdown() which calls token_manager.cleanup() explicitly.
        if hasattr(self, "_token_manager"):
            cli_process = self._token_manager._cli_refresh_process
            if cli_process and cli_process.poll() is None:
                with contextlib.suppress(Exception):
                    cli_process.terminate()
            self._token_manager._cli_refresh_process = None

        # Cancel recovery probe task if running
        # During shutdown, we need to cancel the task without trying to schedule it
        # on the event loop, which may already be closed
        if (
            hasattr(self, "_recovery_probe_task")
            and self._recovery_probe_task
            and not self._recovery_probe_task.done()
        ):
            # Simply cancel without awaiting - the task will be cleaned up
            # We suppress all exceptions because during interpreter shutdown,
            # the logging system may already be torn down
            with contextlib.suppress(Exception):
                self._recovery_probe_task.cancel()
        if hasattr(self, "_recovery_probe_task"):
            self._recovery_probe_task = None
