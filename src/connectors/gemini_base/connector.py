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

if TYPE_CHECKING:

    pass

from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.gemini import GeminiBackend
from src.connectors.gemini_base.chat_request_preparer import (
    ChatRequestPreparer,
)
from src.connectors.gemini_base.config import (
    CODE_ASSIST_ENDPOINT,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    GracefulDegradationConfig,
)
from src.connectors.gemini_base.credential_loader import CredentialLoader
from src.connectors.gemini_base.credentials import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
)

# Strategy interfaces and implementations
from src.connectors.gemini_base.endpoints import StandardCodeAssistEndpoint
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
from src.connectors.gemini_base.interfaces import (
    ICredentialProvider,
    IEndpointConfig,
    IModelDiscoveryStrategy,
    IProjectDiscoveryStrategy,
    IRequestBodyBuilder,
    IResponsePostProcessor,
)
from src.connectors.gemini_base.model_discovery import ApiModelDiscovery
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
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin
from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
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
    """Base class for Gemini OAuth connectors."""

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
        self._oauth_credentials: dict[str, Any] | None = None
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
        self._thought_signature_service = (
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
            except Exception:
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
            self._credentials_path, self, self._file_watcher_state
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
        oauth_creds.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
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
        """Ensure a valid access token is available, refreshing when necessary."""
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
        return await CredentialLoader.load_oauth_credentials(self, force_reload, silent)

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

        # 1) Startup validation pipeline
        # First validate credentials file exists and is readable
        ok, errs = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errs)
            return

        # 2) Load credentials into memory
        if not await self._load_oauth_credentials():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._oauth_credentials is not None:
            ok, errs = self._validate_credentials_structure(self._oauth_credentials)
            if not ok:
                self._fail_init(errs)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        # 4) Refresh if needed
        if not await self._refresh_token_if_needed():
            pending_message = "OAuth token refresh pending; Gemini CLI background refresh was triggered."
            self._degrade([pending_message])
            self._start_file_watching()
            self._initialization_failed = False
            self._last_validation_time = time.time()
            logger.warning(
                "Gemini OAuth Personal backend started with an expired token; "
                "waiting for the Gemini CLI to refresh credentials."
            )
            return

        # 5) Load models (non-fatal)
        try:
            await self._ensure_models_loaded()
        except Exception as e:
            logger.warning(
                f"Failed to load models during initialization: {e}", exc_info=True
            )
            # Continue with initialization even if model loading fails

        # 6) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()

        logger.info(
            f"Gemini OAuth Personal backend initialized successfully with {len(self.available_models)} models."
        )

    async def _ensure_models_loaded(self) -> None:
        """Fetch models if not already cached - OAuth version.

        First tries to load models from the fetchAvailableModels API endpoint.
        Falls back to a hardcoded list if the API call fails.

        Results are cached in self.available_models and self._available_models_set
        to avoid repeated API calls.
        """
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

        Validation is only performed when models were loaded from the API.
        When using the hardcoded fallback list, validation is skipped since
        the hardcoded list may be outdated.

        Args:
            model_name: The model name to validate

        Raises:
            BackendError: If the model is not in the available models list
        """
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
    ) -> dict[str, Any]:
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
                except Exception:
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
            models_list = []
            models_dict = data.get("models", {})
            if isinstance(models_dict, dict):
                for model_id, model_info in models_dict.items():
                    model_entry: dict[str, Any] = {"name": f"models/{model_id}"}
                    if isinstance(model_info, dict):
                        if "displayName" in model_info:
                            model_entry["displayName"] = model_info["displayName"]
                        if "maxTokens" in model_info:
                            model_entry["inputTokenLimit"] = model_info["maxTokens"]
                        if "maxOutputTokens" in model_info:
                            model_entry["outputTokenLimit"] = model_info[
                                "maxOutputTokens"
                            ]

                    models_list.append(model_entry)

            return {"models": models_list}

        except httpx.TimeoutException as e:
            logger.error("Timeout connecting to Gemini OAuth API: %s", e, exc_info=True)
            raise ServiceUnavailableError(
                message=f"Timeout connecting to Gemini OAuth API ({e})"
            )
        except httpx.RequestError as e:
            logger.error(
                "Request error connecting to Gemini OAuth API: %s", e, exc_info=True
            )
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini OAuth API ({e})"
            )

    async def _resolve_gemini_api_config(
        self,
        gemini_api_base_url: str | None,
        openrouter_api_base_url: str | None,
        api_key: str | None,
        **kwargs: Any,
    ) -> tuple[str, dict[str, str]]:
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
        return base.rstrip("/"), {"Authorization": f"Bearer {access_token}"}

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

        This method performs health checks on first use, similar to how
        models are loaded lazily in the parent class.
        """
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
        openrouter_api_base_url: str | None = None,
        openrouter_headers_provider: Any = None,
        key_name: str | None = None,
        api_key: str | None = None,
        project: str | None = None,
        agent: str | None = None,
        gemini_api_base_url: str | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions using Google Code Assist API.

        This method uses the Code Assist API (https://cloudcode-pa.googleapis.com)
        which is the correct endpoint for oauth-personal authentication,
        while maintaining OpenAI-compatible interface and response format.
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
            model_name = self._public_to_internal_model_map.get(model_name, model_name)

            # Check if streaming is requested
            is_streaming = getattr(request_data, "stream", False)

            try:
                # IMPORTANT: The Gemini Code Assist API only supports streaming endpoints
                # (streamGenerateContent). For non-streaming requests, we always use
                # the streaming path internally and accumulate the response.
                # This avoids blocking synchronous calls that cause client timeouts.
                if is_streaming:
                    return await self._chat_completions_code_assist_streaming(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model_name,
                        **kwargs,
                    )
                else:
                    # Use streaming internally but accumulate to non-streaming response
                    # This prevents client timeouts by processing progressively
                    streaming_response = (
                        await self._chat_completions_code_assist_streaming(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_name,
                            **kwargs,
                        )
                    )
                    # Accumulate streaming response into a ResponseEnvelope
                    accumulator = StreamingResponseAccumulator(
                        backend_type=getattr(self, "backend_type", "gemini")
                    )
                    return await accumulator.accumulate(streaming_response)
            except BackendError:
                # Propagate backend errors to be handled by the Resilience Layer.
                raise

        except HTTPException:
            # Re-raise HTTP exceptions directly
            raise
        except AuthenticationError:
            # Re-raise authentication errors
            raise
        except BackendError:
            # Re-raise backend errors (already handled 429 above)
            raise
        except InvalidRequestError:
            # Let context window overflows bubble up for clients to handle
            raise
        except Exception as e:
            # Convert other exceptions to BackendError
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

        This method implements the Code Assist API calls that match the Gemini CLI
        approach, while converting to/from OpenAI-compatible formats.
        """
        try:
            prepared_start = time.monotonic()
            prepared = await self._chat_preparer.prepare(
                request_data=request_data,
                effective_model=effective_model,
                is_streaming=False,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Prepared non-streaming request in %.3fs (model=%s, session=%s)",
                    time.monotonic() - prepared_start,
                    effective_model,
                    getattr(request_data, "session_id", None),
                )

            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making Code Assist API call to: {url}")

            response = await self._orchestrator.run_non_streaming(
                prepared=prepared,
                url=url,
                token_refresher=self,
                thought_signature_callback=self._build_thought_signature_callback(),
                key_name=getattr(self, "_key_name", None),
            )

            logger.info(
                "Successfully received and processed response from Code Assist API"
            )
            return response

        except AuthenticationError as e:
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
            logger.warning("Request blocked locally: %s", e)
            raise
        except Exception as e:
            logger.error(f"Unexpected error during API call: {e}", exc_info=True)
            raise BackendError(f"Unexpected error during API call: {e}")

    async def _chat_completions_code_assist_streaming(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _rate_limit_retry_attempted: bool = False,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions using the Code Assist API.

        This method delegates to the StreamingExecutor for the actual
        streaming HTTP handling, keeping this orchestration method focused
        on setup, VTC wrapping, and error handling.
        """
        from src.core.ports.streaming_contracts import handle_streaming_error

        try:
            # Use ChatRequestPreparer for all common setup
            prepared_start = time.monotonic()
            prepared = await self._chat_preparer.prepare(
                request_data=request_data,
                effective_model=effective_model,
                is_streaming=True,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Prepared streaming request in %.3fs (model=%s, session=%s)",
                    time.monotonic() - prepared_start,
                    effective_model,
                    getattr(request_data, "session_id", None),
                )

            # Use the Code Assist API with streaming endpoint
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making streaming Code Assist API call to: {url}")

            stream_wrapper = self._build_vtc_wrapper(
                request_data=request_data,
                effective_model=effective_model,
            )

            return await self._orchestrator.run_streaming(
                prepared=prepared,
                url=url,
                token_refresher=self,  # Connector implements refresh_token_if_needed
                thought_signature_callback=self._build_thought_signature_callback(),
                key_name=getattr(self, "_key_name", None),
                stream_wrapper=stream_wrapper,
            )

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
                # Yield as string so response_adapters legacy SSE check passes
                yield ProcessedResponse(content=chunk.to_bytes().decode("utf-8"))

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
            logger.warning("Streaming request blocked locally: %s", e)
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error during streaming API call: {e}", exc_info=True
            )
            raise BackendError(f"Unexpected error during streaming API call: {e}")

    def _build_vtc_wrapper(
        self, request_data: Any, effective_model: str
    ) -> StreamWrapper | None:
        """Build VTC wrapper for streaming responses if enabled."""
        vtc_enabled = getattr(request_data, "vtc_enabled", False) or False
        if not vtc_enabled:
            return None

        tool_call_reactor = None
        try:
            from src.core.di.services import get_service_provider
            from src.core.services.tool_call_reactor_service import (
                ToolCallReactorService,
            )

            provider = get_service_provider()
            tool_call_reactor = provider.get_service(ToolCallReactorService)
        except Exception as exc:
            logger.warning("Failed to get tool call reactor for VTC: %s", exc)

        reactor_context = {
            "backend_name": self.backend_type,
            "model_name": effective_model,
            "calling_agent": getattr(request_data, "agent", None),
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
                session_id=session_id,
                context=reactor_context,
            )

        return cast(StreamWrapper, wrapper)

    def _build_thought_signature_callback(
        self,
    ) -> Callable[[list[dict[str, Any]], str | None], None]:
        """Create a thought-signature storage callback for streaming executor."""

        def callback(tool_calls: list[dict[str, Any]], session_id: str | None) -> None:
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
        """Convert OpenAI-style request to Code Assist API format."""
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
        full_prompt = system_prompt
        if conversation_context:
            if full_prompt:
                full_prompt += "\n\n"
            full_prompt += "\n".join(conversation_context)

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
        """
        builder = GenerationConfigBuilder()
        return builder.build(request_data)

    def _convert_from_code_assist_format(
        self, code_assist_response: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert Code Assist API response to OpenAI-compatible format.

        Delegates to convert_from_code_assist_format module function.
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
            logger.debug(f"Probing recovery for model {model}")

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
                logger.info(f"Model {model} recovered from cooldown")
                return True

            logger.debug(f"Model {model} probe {state.probe_success_count}/2 succeeded")

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
                logger.warning(f"Error in recovery probing loop: {e}")

    @abc.abstractmethod
    async def _discover_project_id(self, auth_session) -> str:
        """Discover or retrieve the project ID for Code Assist API."""
        raise NotImplementedError

    def __del__(self):
        """Cleanup file watcher on destruction."""
        # Guard against partial initialization
        if hasattr(self, "_file_watcher_state"):
            self._stop_file_watching()

        # Cleanup CLI refresh process via token manager
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
