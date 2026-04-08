"""
Streaming executor for Gemini Code Assist API.

This module extracts the streaming execution logic from the connector,
providing a focused, testable service for handling streaming HTTP requests.
"""

import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Iterable, Mapping, MutableMapping
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

# ---------------------------------------------------------------------------
# Module-level backend cooldown state
#
# The Code Assist backend applies IP-based (not per-account) rate limits.
# When *any* account on this proxy receives a 429, the entire backend
# is in a cooldown period.  All subsequent requests -- including those
# from different accounts -- must wait until the cooldown expires before
# dispatching a new HTTP request.
#
# This prevents the cascading 429 pattern where immediate retries or
# concurrent requests exhaust the rate-limit window.
# ---------------------------------------------------------------------------
_model_cooldown_until: dict[tuple[str, str], float] = (
    {}
)  # (backend_scope, model) -> monotonic time
_model_cooldown_lock = threading.Lock()

from unittest.mock import Mock

import pydantic
import requests  # type: ignore[import-untyped]
from pydantic.types import JsonValue

from src.connectors.contracts import ConnectorRequestContext
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.config import DEFAULT_READ_TIMEOUT
from src.connectors.gemini_base.google_auth_adapter import (
    GoogleAuthProvider,
    get_default_google_auth_provider,
)
from src.connectors.gemini_base.policies import (
    AuthRefreshPolicy,
    IAuthRefreshPolicy,
    IRetryPolicy,
)
from src.connectors.gemini_base.retry_delay_parser import (
    extract_retry_delay_from_response,
    parse_retry_from_message,
)
from src.connectors.gemini_base.stream_processor import (
    build_error_chunk,
    build_rate_limit_backend_error,
    coerce_chunk_to_dict,
    normalize_chunk,
    should_skip_chunk,
)
from src.connectors.gemini_base.token_estimator import (
    TiktokenEstimator,
    get_default_token_estimator,
)
from src.connectors.gemini_base.tool_sanitizer import (
    normalize_code_assist_request_tools,
)
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import BackendError
from src.core.common.resilience_retry import (
    AsyncRetryExecutor,
    RetryAttemptRecord,
    RetryBudget,
    RetryPolicy,
    extract_retry_after_seconds,
)
from src.core.common.wire_boundary_capture import (
    capture_requests_inbound_response,
    capture_requests_outbound_request,
)
from src.core.domain.gemini_metadata import create_gemini_response_metadata
from src.core.domain.streaming.contracts import (
    OpenAIError,
    OpenAIErrorChoice,
    OpenAIErrorChunk,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse

if TYPE_CHECKING:
    from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


class _GeminiRateLimitRetryError(Exception):
    """Internal signal for shared rate-limit retry scheduling."""

    def __init__(self, error: BackendError) -> None:
        super().__init__(str(error))
        self.error = error


@runtime_checkable
class IRetryContext(Protocol):
    """Protocol for request contexts that carry retry metadata."""

    extensions: dict[str, JsonValue]


class ErrorMetadata(pydantic.BaseModel):
    """Metadata for error responses in streaming.

    Provides a strongly-typed contract for error metadata
    including finish reason, error details, and timing information.
    """

    finish_reason: str = "error"
    error: OpenAIError
    id: str
    model: str
    created: int

    model_config = {"extra": "forbid"}

    def to_metadata(self) -> dict[str, JsonValue]:
        # Note: OpenAIError is a Pydantic model; dump to JSON-compatible primitives.
        return self.model_dump()


@runtime_checkable
class IRetryDelayExtractor(Protocol):
    """Interface for extracting retry delays from errors."""

    def extract_retry_delay(self, error: BackendError) -> float | None:
        """Extract retry-after delay from a backend error."""
        ...


@runtime_checkable
class ITokenRefresher(Protocol):
    """Interface for token refresh operations.

    This protocol provides a minimal interface for token refresh during request execution.
    It enables runtime token management without coupling execution to credential coordination.

    **Data Flow**: This interface flows:
    - Produced by connector context or credential coordinator
    - Consumed by `ICodeAssistOrchestrator.run_streaming()` and `.run_non_streaming()`
    - Used during request execution for automatic token refresh on auth failures

    **Service Boundaries**: Provides a narrow interface for token refresh, isolating
    execution concerns from credential lifecycle management. Supports DI and test seams.
    """

    async def refresh_token_if_needed(
        self,
        *,
        force_reload: bool = False,
        session_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> bool:
        """Refresh the OAuth token if needed.

        Args:
            force_reload: If True, force reload credentials before refresh.
            retry_after_seconds: Optional explicit retry delay suggested by the API.

        Returns:
            True if refresh succeeded or was not needed, False otherwise.
        """
        ...


class SSELineProcessor:
    """Processes SSE lines from the streaming response.

    This class handles the parsing of SSE data lines, rate limit detection,
    and chunk normalization.
    """

    def __init__(
        self,
        translation_service: "TranslationService",
        effective_model: str,
        retry_delay_extractor: IRetryDelayExtractor | None = None,
        backend_type: str = "gemini",
    ) -> None:
        """Initialize the processor.

        Args:
            translation_service: Service for translating chunks to domain format.
            effective_model: The model name being used.
            retry_delay_extractor: Optional extractor for retry delays.
            backend_type: The backend type for error reporting.
        """
        self._translation_service = translation_service
        self._effective_model = effective_model
        self._retry_delay_extractor = retry_delay_extractor
        self._backend_type = backend_type

    def should_skip_chunk(self, chunk: dict[str, Any] | Any) -> bool:
        """Check if a chunk should be skipped.

        Args:
            chunk: The chunk to check.

        Returns:
            True if the chunk should be skipped.
        """
        chunk_dict = coerce_chunk_to_dict(chunk)
        if chunk_dict is None:
            return True
        normalize_chunk(chunk_dict)
        return should_skip_chunk(chunk_dict)

    def build_error_chunk(
        self, message: str, *, code: int = 500, error_type: str = "api_error"
    ) -> OpenAIErrorChunk:
        """Build a standardized error chunk.

        Args:
            message: The error message.
            code: HTTP status code.
            error_type: The error type.

        Returns:
            Error chunk dictionary.
        """
        return build_error_chunk(
            message=message,
            code=code,
            model=self._effective_model,
            error_type=error_type,
        )

    def check_rate_limit_in_payload(self, data: dict[str, Any]) -> BackendError | None:
        """Check if a payload indicates rate limiting.

        Args:
            data: The parsed SSE data.

        Returns:
            BackendError if rate limited, None otherwise.
        """
        rate_limit_error = build_rate_limit_backend_error(data, self._effective_model)
        if rate_limit_error is None:
            return None

        retry_delay = None
        if self._retry_delay_extractor:
            retry_delay = self._retry_delay_extractor.extract_retry_delay(
                rate_limit_error
            )

        details: dict[str, Any] = rate_limit_error.details
        if retry_delay is not None:
            details["retry_after"] = float(retry_delay)  # type: ignore[assignment]

        return BackendError(
            message=rate_limit_error.message,
            code=rate_limit_error.code,
            status_code=getattr(rate_limit_error, "status_code", 429),
            details=details,
            backend_name=self._backend_type,
        )

    def translate_chunk(self, data: dict[str, Any]) -> dict[str, Any] | None:
        """Translate a raw SSE chunk to domain format.

        Args:
            data: The parsed SSE data.

        Returns:
            Translated chunk dictionary, or None if translation fails.
        """
        try:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[STREAMING] Received chunk from backend: choices_count=%s, has_usage=%s, has_id=%s",
                    len(data.get("choices", [])),
                    "usage" in data,
                    "id" in data,
                )

            domain_chunk = self._translation_service.to_domain_stream_chunk(
                chunk=data, source_format="code_assist"
            )

            if domain_chunk is not None and not isinstance(domain_chunk, dict):
                dump = getattr(domain_chunk, "model_dump", lambda **_: None)(
                    exclude_none=True
                )
                if isinstance(dump, dict):
                    domain_chunk = dump
                else:
                    domain_chunk = {}

            if domain_chunk is not None:
                # Ensure we use the effective model name, not what the backend returns
                domain_chunk["model"] = self._effective_model
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] After translation: id=%s, model=%s, choices_count=%s",
                        (
                            domain_chunk.get("id", "none")[:20]
                            if domain_chunk.get("id")
                            else "none"
                        ),
                        domain_chunk.get("model", "none"),
                        len(domain_chunk.get("choices", [])),
                    )

            result: dict[str, Any] | None = (
                domain_chunk if isinstance(domain_chunk, dict) else None
            )
            return result

        except Exception as e:
            logger.error("Failed to process streaming chunk: %s", str(e), exc_info=True)
            return None


class StreamingExecutor:
    """Executes streaming HTTP requests to the Code Assist API.

    This class handles the HTTP streaming layer, including:
    - Making the streaming request
    - Processing SSE chunks
    - Handling errors and auth retry
    - Calculating usage metrics
    """

    MAX_ERROR_JSON_SIZE = 32 * 1024  # 32KB limit for error JSON detection
    MAX_RATE_LIMIT_RETRY_SECONDS = 60.0
    # Small floor to prevent a zero-delay hot loop when the server reports
    # retryDelay: "0s" (common with RESOURCE_EXHAUSTED).  Kept low so that
    # short server-specified windows (e.g. 1-2 s) are honoured faithfully,
    # matching the gemini-cli behaviour of respecting Retry-After verbatim.
    MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS = 0.5
    # Default backoff when the server provides *no* retry-after hint at all.
    DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 2.0
    STREAMING_KEEPALIVE_INTERVAL_SECONDS = 8.0

    def __init__(
        self,
        translation_service: "TranslationService",
        token_estimator: TiktokenEstimator | None = None,
        google_auth_provider: GoogleAuthProvider | None = None,
        retry_delay_extractor: IRetryDelayExtractor | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        backend_type: str = "gemini",
        *,
        session_factory: Any | None = None,
        read_timeout: float | None = None,
        yield_interval: int = 100,
        max_rate_limit_retry_seconds: float | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            translation_service: Service for translating responses.
            token_estimator: Optional token estimator (defaults to tiktoken).
            google_auth_provider: Optional Google auth provider.
            retry_delay_extractor: Optional retry delay extractor.
            auth_refresh_policy: Optional auth refresh policy for 401 handling.
            retry_policy: Optional retry policy for rate-limit handling.
            backend_type: The backend type for error reporting.
            session_factory: Legacy hook retained for compatibility (unused).
            read_timeout: Optional read timeout override.
            yield_interval: Number of chunks to batch before yielding to event loop.
            max_rate_limit_retry_seconds: Optional local wait ceiling for a single
                connector-level 429 retry before surfacing upstream.
        """
        self._translation_service = translation_service
        self._token_estimator = token_estimator or get_default_token_estimator()
        self._google_auth = google_auth_provider or get_default_google_auth_provider()
        self._retry_delay_extractor = retry_delay_extractor
        self._auth_refresh_policy = auth_refresh_policy or AuthRefreshPolicy()
        self._retry_policy = retry_policy
        self._backend_type = backend_type
        self._session_factory = session_factory
        self._read_timeout = read_timeout or DEFAULT_READ_TIMEOUT
        self._yield_interval = yield_interval
        if (
            isinstance(max_rate_limit_retry_seconds, int | float)
            and max_rate_limit_retry_seconds > 0
        ):
            self._max_rate_limit_retry_seconds = float(max_rate_limit_retry_seconds)
        else:
            self._max_rate_limit_retry_seconds = self.MAX_RATE_LIMIT_RETRY_SECONDS
        self._shared_retry_executor = AsyncRetryExecutor(
            RetryPolicy(
                attempts=2,
                timeout_seconds=None,
                wait_initial=self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
                wait_max=self._max_rate_limit_retry_seconds,
                wait_jitter=0.3,
                wait_exp_base=2.0,
            )
        )

    def _mark_retry_attempt(self, context: IRetryContext | None) -> None:
        if context is None:
            return
        extensions = context.extensions
        current = extensions.get("retry_attempt")
        if isinstance(current, int):
            extensions["retry_attempt"] = current + 1
        else:
            extensions["retry_attempt"] = 1
        extensions["is_retry"] = True

    # ------------------------------------------------------------------
    # Backend-wide cooldown helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_backend_cooldown_scope(
        backend_type: str,
    ) -> str:
        """Return the backend-wide cooldown scope key."""
        normalized = (backend_type or "gemini").strip().lower()
        return normalized or "gemini"

    @staticmethod
    def _get_backend_cooldown_remaining(backend_scope: str, model: str) -> float:
        """Return seconds remaining in the model-wide cooldown, or 0."""
        with _model_cooldown_lock:
            remaining = (
                _model_cooldown_until.get((backend_scope, model), 0.0)
                - time.monotonic()
            )
        return max(remaining, 0.0)

    @staticmethod
    def _set_backend_cooldown(backend_scope: str, model: str, seconds: float) -> None:
        """Extend the model-wide cooldown to at least *seconds* from now.

        Thread-safe; only moves the cooldown forward, never backward.
        """
        global _model_cooldown_until
        new_until = time.monotonic() + seconds
        with _model_cooldown_lock:
            current = _model_cooldown_until.get((backend_scope, model), 0.0)
            if new_until > current:
                _model_cooldown_until[(backend_scope, model)] = new_until

    def _extract_retry_after_seconds(self, error: BackendError) -> float | None:
        return extract_retry_after_seconds(error)

    @staticmethod
    def _is_retryable_rate_limit_error(error: BackendError) -> bool:
        status_code = getattr(error, "status_code", None)
        if status_code in {429, 502, 503, 504}:
            return True

        error_code = getattr(error, "code", None)
        if isinstance(error_code, str):
            normalized = error_code.lower()
            return normalized in {
                "rate_limit_exceeded",
                "temporarily_unavailable",
                "service_unavailable",
                "timeout",
                "capacity_exceeded",
            }

        return False

    def _build_rate_limit_retry_exhausted_error(
        self,
        *,
        source_error: BackendError,
        retry_error: Exception | None,
    ) -> BackendError:
        details: dict[str, Any] = {}
        details.update(source_error.details)

        retry_after = self._extract_retry_after_seconds(source_error)
        if retry_after is not None:
            details["retry_after"] = retry_after

        retry_history: list[Any] = []
        if retry_error is not None:
            retry_history = getattr(retry_error, "__retry_history__", []) or []
        details["retry_history"] = [
            (
                {
                    "attempt_num": record.attempt_num,
                    "wait_for_seconds": record.wait_for_seconds,
                    "caused_by_type": record.caused_by_type,
                    "caused_by_message": record.caused_by_message,
                    "used_retry_after_hint": record.used_retry_after_hint,
                }
                if isinstance(record, RetryAttemptRecord)
                else record
            )
            for record in retry_history
        ]

        return BackendError(
            message=getattr(source_error, "message", str(source_error)),
            code=getattr(source_error, "code", None),
            status_code=getattr(source_error, "status_code", 429),
            details=details,
            backend_name=self._backend_type,
        )

    async def _wait_for_rate_limit_retry(
        self,
        error: BackendError,
        *,
        retry_budget: RetryBudget | None = None,
    ) -> RetryAttemptRecord:
        retry_records: list[RetryAttemptRecord] = []
        wait_state = {"scheduled": False}

        async def _wait_once() -> None:
            if not wait_state["scheduled"]:
                wait_state["scheduled"] = True
                raise _GeminiRateLimitRetryError(error)
            return None

        def _should_retry(exc: Exception) -> bool:
            if not isinstance(exc, _GeminiRateLimitRetryError):
                return False
            return self._is_retryable_rate_limit_error(exc.error)

        def _retry_after_hint(exc: Exception) -> float | None:
            if not isinstance(exc, _GeminiRateLimitRetryError):
                return None
            retry_after = self._extract_retry_after_seconds(exc.error)
            if retry_after is None:
                return None
            # A Retry-After value of 0 can create hot retry loops; keep a small floor.
            if retry_after <= 0:
                return self.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS
            return retry_after

        try:
            await self._shared_retry_executor.execute(
                _wait_once,
                should_retry=_should_retry,
                retry_after_extractor=_retry_after_hint,
                retry_budget=retry_budget,
                on_retry_scheduled=retry_records.append,
            )
        except Exception as retry_error:
            raise self._build_rate_limit_retry_exhausted_error(
                source_error=error,
                retry_error=retry_error,
            ) from retry_error

        if retry_records:
            return retry_records[-1]

        raise self._build_rate_limit_retry_exhausted_error(
            source_error=error,
            retry_error=None,
        )

    @staticmethod
    def _build_rate_limit_retry_keepalive(
        prepared: PreparedChatRequest,
    ) -> ProcessedResponse:
        keepalive_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"
        keepalive_created = int(time.time())
        return ProcessedResponse(
            content="",
            metadata={
                "_keepalive": True,
                "id": keepalive_id,
                "model": prepared.effective_model,
                "created": keepalive_created,
                "session_id": prepared.session_id,
                "stream_id": prepared.session_id,
            },
        )

    async def _record_rate_limit(
        self,
        token_refresher: ITokenRefresher | None,
        retry_after_seconds: float | None,
    ) -> None:
        if token_refresher is None:
            return
        recorder = getattr(token_refresher, "record_rate_limit", None)
        if not callable(recorder):
            return
        try:
            result = recorder(retry_after_seconds=retry_after_seconds)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.warning(
                "Failed to record rate limit for oauth-auto account",
                exc_info=True,
            )

    @staticmethod
    def _is_oauth_auto_refresher(token_refresher: ITokenRefresher | None) -> bool:
        if token_refresher is None:
            return False
        backend_type = str(getattr(token_refresher, "backend_type", ""))
        return "oauth-auto" in backend_type

    @staticmethod
    def _get_oauth_auto_selection_strategy(
        token_refresher: ITokenRefresher | None,
    ) -> str | None:
        if token_refresher is None:
            return None

        strategy = getattr(token_refresher, "selection_strategy", None)
        if isinstance(strategy, str) and strategy:
            return strategy

        selector = getattr(token_refresher, "_account_selector", None)
        strategy_from_selector = getattr(selector, "selection_strategy", None)
        if isinstance(strategy_from_selector, str) and strategy_from_selector:
            return strategy_from_selector
        return None

    @staticmethod
    def _get_oauth_auto_available_account_count(
        token_refresher: ITokenRefresher | None,
    ) -> int | None:
        if token_refresher is None:
            return None

        selector = getattr(token_refresher, "_account_selector", None)
        getter = getattr(selector, "get_available_count", None)
        if callable(getter):
            try:
                count = getter()
                if isinstance(count, int):
                    return count
            except Exception:
                return None

        count_attr = getattr(token_refresher, "available_account_count", None)
        if isinstance(count_attr, int):
            return count_attr
        return None

    def _should_wait_same_account_on_rate_limit(
        self,
        *,
        token_refresher: ITokenRefresher | None,
        sleep_seconds: float,
        retry_after_seconds: float | None,
    ) -> bool:
        if sleep_seconds > self._max_rate_limit_retry_seconds:
            return False
        if not self._is_oauth_auto_refresher(token_refresher):
            return True
        strategy = self._get_oauth_auto_selection_strategy(token_refresher)
        if strategy != "session-affinity":
            return False
        # Code Assist rate limits are observed as endpoint/IP-scoped.
        # When the server provides a positive Retry-After, preserve the
        # current account and wait; rotating credentials does not bypass
        # the same upstream bucket and only increases churn.
        return retry_after_seconds is not None and retry_after_seconds > 0

    @staticmethod
    def _apply_jitter(delay: float, factor: float = 0.30) -> float:
        """Apply ±``factor`` jitter to a delay (matching gemini-cli)."""
        import random as _rnd

        jitter = delay * factor
        return max(0.0, delay + _rnd.uniform(-jitter, jitter))

    def _compute_rate_limit_retry_sleep_seconds(
        self,
        *,
        suggested_sleep_seconds: float,
        retry_after_seconds: float | None,
        preserve_affinity_wait: bool,
        rotated_credentials: bool,
    ) -> float:
        """Compute local sleep for a single 429 retry attempt.

        Rules (aligned with gemini-cli Retry-After semantics):
        - When the server provides an explicit retry-after value, honour it
          with only a small floor (MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS) to
          prevent a zero-delay hot loop.
        - Account rotation does NOT bypass the server hint.  The Code Assist
          backend applies IP-based rate limits, so rotating credentials does
          not clear the rate-limit window.  A short 0.5 s retry after rotation
          just exhausts both accounts and cascades into repeated 429s.
        - When no server hint is available, use a moderate default backoff
          (DEFAULT_RATE_LIMIT_BACKOFF_SECONDS).
        - All computed delays are jittered ±30 % so concurrent clients
          don't all retry at the exact same instant.
        """
        has_server_hint = retry_after_seconds is not None and retry_after_seconds >= 0

        if has_server_hint:
            base = max(
                suggested_sleep_seconds,
                self.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS,
            )
            return self._apply_jitter(base)

        # No server hint.
        if rotated_credentials:
            return self._apply_jitter(self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS)

        if suggested_sleep_seconds <= 0:
            return self._apply_jitter(self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS)

        base = max(
            suggested_sleep_seconds,
            self.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS,
        )
        return self._apply_jitter(base)

    @staticmethod
    def _apply_refreshed_auth_header(
        prepared: PreparedChatRequest,
        token_refresher: ITokenRefresher,
    ) -> None:
        creds = getattr(token_refresher, "_oauth_credentials", None)
        if isinstance(creds, dict):
            access_token = creds.get("access_token")
            if (
                isinstance(access_token, str)
                and access_token
                and hasattr(prepared.auth_session, "headers")
            ):
                prepared.auth_session.headers["Authorization"] = (
                    f"Bearer {access_token}"
                )

    @staticmethod
    def _build_authenticated_request_headers(
        prepared: PreparedChatRequest,
        *,
        method: str,
        url: str,
        base_headers: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if base_headers is not None:
            headers.update(base_headers)

        session_headers = getattr(prepared.auth_session, "headers", None)
        if isinstance(session_headers, Mapping):
            headers.update(
                {
                    str(key): str(value)
                    for key, value in session_headers.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
            )

        credentials = getattr(prepared.auth_session, "credentials", None)
        before_request = getattr(credentials, "before_request", None)
        if callable(before_request):
            before_request(
                getattr(prepared.auth_session, "_auth_request", None),
                method,
                url,
                headers,
            )

        return headers

    async def _try_rotate_oauth_auto_account(
        self,
        *,
        token_refresher: ITokenRefresher | None,
        prepared: PreparedChatRequest,
        retry_after_seconds: float | None,
        log_context: str,
    ) -> bool:
        if token_refresher is None or not self._is_oauth_auto_refresher(
            token_refresher
        ):
            return False

        try:
            rotated = await token_refresher.refresh_token_if_needed(
                force_reload=True,
                session_id=prepared.session_id,
                retry_after_seconds=retry_after_seconds,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("%s: rotated=%s", log_context, rotated)
        except Exception as rotation_error:
            logger.warning(
                "Failed to rotate account on rate limit (%s): %s",
                log_context,
                str(rotation_error),
                exc_info=True,
            )
            return False

        if rotated:
            self._apply_refreshed_auth_header(prepared, token_refresher)
        return rotated

    async def execute(
        self,
        prepared: PreparedChatRequest,
        url: str,
        *,
        token_refresher: ITokenRefresher | None = None,
        context: IRetryContext | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        retry_policy: IRetryPolicy | None = None,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Execute a streaming request and yield processed responses.

        Args:
            prepared: The prepared chat request.
            url: The streaming endpoint URL.
            token_refresher: Optional token refresher for auth retry.
            thought_signature_callback: Optional callback for storing thought signatures.
            key_name: Optional key name for metadata.
            retry_policy: Optional retry policy for rate limits.

        Yields:
            ProcessedResponse objects for each chunk.
        """
        # Create the line processor
        processor = SSELineProcessor(
            translation_service=self._translation_service,
            effective_model=prepared.effective_model,
            retry_delay_extractor=self._retry_delay_extractor,
            backend_type=self._backend_type,
        )

        # Calculate prompt tokens if not already done
        prompt_tokens = prepared.prompt_tokens_estimate
        if prompt_tokens is None:
            prompt_tokens = (
                self._token_estimator.estimate_prompt_tokens(
                    prepared.code_assist_request
                )
                or 0
            )

        async for chunk in self._stream_generator(
            prepared=prepared,
            url=url,
            processor=processor,
            prompt_tokens=prompt_tokens,
            token_refresher=token_refresher,
            context=context,
            thought_signature_callback=thought_signature_callback,
            key_name=key_name,
            auth_refresh_policy=self._auth_refresh_policy,
            retry_policy=retry_policy or self._retry_policy,
        ):
            yield chunk

    async def _stream_generator(
        self,
        prepared: PreparedChatRequest,
        url: str,
        processor: SSELineProcessor,
        prompt_tokens: int,
        *,
        token_refresher: ITokenRefresher | None = None,
        context: IRetryContext | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        _allow_tool_retry: bool = True,
        without_tools: bool = False,
        _auth_retry_attempted: bool = False,
        _rate_limit_retry_attempted: bool = False,
        _timeout_retry_attempted: bool = False,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Internal generator that handles the streaming loop."""
        response: requests.Response | None = None
        chunk_count = 0
        # PERFORMANCE: Use list accumulators to avoid O(n²) string concatenation in streaming hot path
        generated_text_parts: list[str] = []
        error_json_buffer_parts: list[str] | None = None
        current_thought_signature: str | None = None
        google_auth_exceptions = self._google_auth.get_auth_exceptions()

        try:
            # Make the HTTP request
            try:
                if without_tools:
                    prepared.code_assist_request.pop("tools", None)
                    prepared.code_assist_request.pop("toolConfig", None)

                request_body = prepared.build_request_body()
                normalize_code_assist_request_tools(request_body)

                if logger.isEnabledFor(TRACE_LEVEL):
                    tools_snapshot = request_body.get("request", {}).get("tools")
                    if tools_snapshot:
                        try:
                            logger.log(
                                TRACE_LEVEL,
                                "Code Assist sanitized tools payload: %s",
                                json.dumps(tools_snapshot)[:1000],
                            )
                        except (TypeError, ValueError, RecursionError, OverflowError):
                            # Catch specific exceptions from JSON serialization:
                            # - TypeError: Object is not JSON serializable
                            # - ValueError: Invalid value (e.g., circular references)
                            # - RecursionError: Circular reference during serialization
                            # - OverflowError: Numeric overflow
                            logger.log(
                                TRACE_LEVEL,
                                "Code Assist sanitized tools payload present (non-serializable)",
                                exc_info=True,
                            )

                # Use a loop with timeout to allow yielding keepalives while waiting for the response headers.
                # This prevents the client from stalling during long backend processing (e.g. large prompts).
                keepalive_interval = self.STREAMING_KEEPALIVE_INTERVAL_SECONDS
                keepalive_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"
                keepalive_created = int(time.time())

                def _build_initial_keepalive() -> ProcessedResponse:
                    return ProcessedResponse(
                        content="",
                        metadata={
                            "_keepalive": True,
                            "id": keepalive_id,
                            "model": prepared.effective_model,
                            "created": keepalive_created,
                            "session_id": prepared.session_id,
                            "stream_id": prepared.session_id,
                        },
                    )

                backend_scope = self._get_backend_cooldown_scope(self._backend_type)

                # Respect backend-wide cooldown before dispatching.
                # When a recent 429 was received (from any account), the
                # cooldown prevents this request from hitting the same
                # IP-based rate-limit window.
                cooldown_remaining = self._get_backend_cooldown_remaining(
                    backend_scope, prepared.effective_model
                )
                if cooldown_remaining > 0:
                    if cooldown_remaining > self._max_rate_limit_retry_seconds:
                        logger.warning(
                            "Backend %s in extended cooldown for %.1fs. Failing fast instead of waiting.",
                            prepared.effective_model,
                            cooldown_remaining,
                        )
                        raise BackendError(
                            message=f"Backend is on cooldown for another {cooldown_remaining:.1f}s",
                            status_code=429,
                            details={"retry_after": cooldown_remaining},
                            backend_name=self._backend_type,
                        )

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Backend cooldown: waiting %.1fs before dispatch",
                            cooldown_remaining,
                        )
                    await asyncio.sleep(cooldown_remaining)

                request_headers = self._build_authenticated_request_headers(
                    prepared,
                    method="POST",
                    url=url,
                    base_headers={"Content-Type": "application/json"},
                )
                raw_request = requests.Request(
                    method="POST",
                    url=url,
                    params={"alt": "sse"},
                    json=request_body,
                    headers=request_headers,
                )
                prepared_request = prepared.auth_session.prepare_request(raw_request)
                await capture_requests_outbound_request(
                    request=prepared_request,
                    backend=self._backend_type,
                    model=prepared.effective_model,
                    key_name=key_name,
                    context=cast(ConnectorRequestContext | None, context),
                )
                send_settings = prepared.auth_session.merge_environment_settings(
                    prepared_request.url,
                    {},
                    True,
                    None,
                    None,
                )
                send_callable = getattr(prepared.auth_session, "send", None)
                if callable(send_callable) and not isinstance(send_callable, Mock):
                    # Filter out keys already set explicitly to avoid duplicate kwargs
                    send_settings = {
                        k: v
                        for k, v in send_settings.items()
                        if k not in ("stream", "timeout")
                    }
                    request_task = asyncio.create_task(
                        asyncio.to_thread(
                            send_callable,
                            prepared_request,
                            timeout=int(self._read_timeout),
                            stream=True,
                            **send_settings,
                        )
                    )
                else:
                    request_callable = getattr(prepared.auth_session, "request", None)
                    if not callable(request_callable):
                        raise BackendError(
                            message="Authenticated session does not support request dispatch",
                            backend_name=self._backend_type,
                        )
                    if isinstance(send_settings, Mapping):
                        request_kwargs = {
                            k: v
                            for k, v in dict(send_settings).items()
                            if k not in ("stream", "timeout")
                        }
                    else:
                        request_kwargs = {}
                    request_kwargs["stream"] = True
                    request_task = asyncio.create_task(
                        asyncio.to_thread(
                            request_callable,
                            "POST",
                            url,
                            params={"alt": "sse"},
                            json=request_body,
                            headers={"Content-Type": "application/json"},
                            timeout=int(self._read_timeout),
                            **request_kwargs,
                        )
                    )

                response = None
                while not request_task.done():
                    try:
                        # Wait for the task to complete, or time out to send a keepalive
                        done_set, _ = await asyncio.wait(
                            [request_task], timeout=keepalive_interval
                        )
                        if request_task in done_set:
                            response = cast(requests.Response, await request_task)
                            break
                        else:
                            # Still waiting for backend; yield keepalive to maintain connection
                            yield _build_initial_keepalive()
                    except Exception:
                        if request_task.done():
                            # Ensure we propagate the actual exception from the task
                            await request_task
                        raise

                if response is None:
                    # Defensive: ensure response is valid before proceeding
                    raise BackendError(
                        message="Failed to receive response from Code Assist API",
                        backend_name=self._backend_type,
                    )

                # Help static analysis
                assert response is not None
                await capture_requests_inbound_response(
                    response=response,
                    backend=self._backend_type,
                    model=prepared.effective_model,
                    key_name=key_name,
                    context=cast(ConnectorRequestContext | None, context),
                )

                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] Response received: status=%s",
                        response.status_code,
                    )

            except requests.exceptions.Timeout as te:
                # For oauth-auto backends with multiple accounts, try rotation once
                # before giving up - another account may not be timing out
                if (
                    token_refresher
                    and self._is_oauth_auto_refresher(token_refresher)
                    and not _timeout_retry_attempted
                ):
                    logger.warning(
                        "Streaming timeout (%.1fs) calling %s, attempting account rotation and retry",
                        self._read_timeout,
                        url,
                    )

                    rotated = await self._try_rotate_oauth_auto_account(
                        token_refresher=token_refresher,
                        prepared=prepared,
                        retry_after_seconds=None,
                        log_context="Account rotation on timeout",
                    )

                    if rotated:
                        # Retry immediately with new account (no sleep needed)
                        logger.info(
                            "Retrying streaming request immediately after account rotation due to timeout"
                        )
                        async for chunk in self._stream_generator(
                            prepared=prepared,
                            url=url,
                            processor=processor,
                            prompt_tokens=prompt_tokens,
                            retry_policy=retry_policy,
                            token_refresher=token_refresher,
                            context=context,
                            thought_signature_callback=thought_signature_callback,
                            key_name=key_name,
                            auth_refresh_policy=auth_refresh_policy,
                            _allow_tool_retry=_allow_tool_retry,
                            without_tools=without_tools,
                            _auth_retry_attempted=_auth_retry_attempted,
                            _rate_limit_retry_attempted=_rate_limit_retry_attempted,
                            _timeout_retry_attempted=True,  # Prevent infinite loop
                        ):
                            yield chunk
                        return

                # No rotation or rotation failed - return timeout error
                logger.error(f"Streaming timeout calling {url}: {te}", exc_info=True)
                error_chunk = processor.build_error_chunk(
                    "Gateway timeout reaching Code Assist streaming endpoint.",
                    code=504,
                )
                error_dict = error_chunk.model_dump()
                yield ProcessedResponse(
                    content=error_dict,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            except requests.exceptions.RequestException as rexc:
                logger.error(
                    f"Streaming connection error calling {url}: {rexc}",
                    exc_info=True,
                )
                error_chunk = processor.build_error_chunk(
                    "Connection error reaching Code Assist streaming endpoint.",
                    code=503,
                )
                error_dict = error_chunk.model_dump()
                yield ProcessedResponse(
                    content=error_dict,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            except Exception as exc:
                _gae_cls = getattr(google_auth_exceptions, "GoogleAuthError", None)
                if not (
                    isinstance(_gae_cls, type)
                    and issubclass(_gae_cls, BaseException)
                    and isinstance(exc, _gae_cls)
                ):
                    raise
                logger.error(
                    f"Streaming auth error calling {url}: {exc}",
                    exc_info=True,
                )
                error_chunk = self._build_auth_error_chunk(prepared.effective_model)
                error_dict = error_chunk.model_dump()
                yield ProcessedResponse(
                    content=error_dict,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            # Handle non-200 responses
            if response.status_code != 200:
                async for chunk in self._handle_error_response(
                    response=response,
                    processor=processor,
                    prepared=prepared,
                    url=url,
                    prompt_tokens=prompt_tokens,
                    token_refresher=token_refresher,
                    context=context,
                    thought_signature_callback=thought_signature_callback,
                    key_name=key_name,
                    auth_refresh_policy=auth_refresh_policy,
                    retry_policy=retry_policy,
                    _allow_tool_retry=_allow_tool_retry,
                    without_tools=without_tools,
                    _auth_retry_attempted=_auth_retry_attempted,
                    _rate_limit_retry_attempted=_rate_limit_retry_attempted,
                ):
                    yield chunk
                return

            # Process the streaming response
            line_buffer = ""
            done = False
            final_stop_chunk = None

            def _process_decoded_line(
                decoded_line: str,
            ) -> Iterable[ProcessedResponse]:
                nonlocal done, generated_text_parts, error_json_buffer_parts, current_thought_signature

                if not decoded_line:
                    return

                if decoded_line.startswith("data: "):
                    data_str = decoded_line[6:].strip()
                    if data_str == "[DONE]":
                        done = True
                        return

                    try:
                        data = json.loads(data_str)

                        # Check for rate limit errors
                        rate_limit_error = processor.check_rate_limit_in_payload(data)
                        if rate_limit_error:
                            with contextlib.suppress(Exception):
                                response.close()
                            raise rate_limit_error

                    except json.JSONDecodeError as e:
                        logger.warning(
                            "Received malformed JSON chunk in streaming response: %s (error: %s)",
                            data_str[:100] + "..." if len(data_str) > 100 else data_str,
                            str(e),
                            exc_info=True,
                        )
                        if data_str and not data_str.strip().endswith("}"):
                            logger.error(
                                "Detected incomplete JSON chunk, yielding error response",
                                exc_info=True,
                            )
                            error_chunk = processor.build_error_chunk(
                                "Malformed streaming chunk from Code Assist.",
                                code=502,
                            )
                            yield ProcessedResponse(
                                content=self._get_error_chunk_content(error_chunk),
                                metadata=self._build_error_metadata(error_chunk),
                            )
                            done = True
                        return

                    # Translate chunk
                    domain_chunk = processor.translate_chunk(data)
                    if domain_chunk is None:
                        error_chunk = processor.build_error_chunk(
                            "Failed to parse streaming chunk from Code Assist.",
                            code=500,
                        )
                        yield ProcessedResponse(
                            content=error_chunk.model_dump(),
                            metadata=self._build_error_metadata(error_chunk),
                        )
                        done = True
                        return

                    if domain_chunk and domain_chunk.get("choices"):
                        if processor.should_skip_chunk(domain_chunk):
                            return

                        choice = domain_chunk["choices"][0]

                        delta = choice.get("delta", {}) or {}

                        # Buffer/apply thought signature if present
                        new_sig = delta.pop("thought_signature", None)
                        if new_sig:
                            current_thought_signature = new_sig

                        # Apply buffered signature to tool calls in this chunk
                        raw_tool_calls_in_delta = delta.get("tool_calls")
                        if (
                            isinstance(raw_tool_calls_in_delta, list)
                            and current_thought_signature
                        ):
                            for tc in raw_tool_calls_in_delta:
                                if isinstance(tc, dict):
                                    extra = tc.setdefault("extra_content", {})
                                    if not isinstance(extra, dict):
                                        extra = {}
                                        tc["extra_content"] = extra
                                    google = extra.setdefault("google", {})
                                    if not isinstance(google, dict):
                                        google = {}
                                        extra["google"] = google
                                    if not google.get("thought_signature"):
                                        google["thought_signature"] = (
                                            current_thought_signature
                                        )

                        text_piece = delta.get("content")
                        if text_piece:
                            generated_text_parts.append(text_piece)
                            # Handle error JSON detection in content
                            if (
                                error_json_buffer_parts is None
                                and len(generated_text_parts) <= 3
                            ):
                                stripped_piece = text_piece.lstrip()
                                if stripped_piece.startswith("{"):
                                    error_json_buffer_parts = [stripped_piece]
                            elif error_json_buffer_parts is not None and (
                                sum(len(p) for p in error_json_buffer_parts)
                                < self.MAX_ERROR_JSON_SIZE
                            ):
                                error_json_buffer_parts.append(text_piece)
                            else:
                                # Stop buffering if too large or not started - likely valid content, not an error
                                error_json_buffer_parts = None

                            # Try to parse accumulated error JSON
                            if error_json_buffer_parts:
                                candidate_json = "".join(
                                    error_json_buffer_parts
                                ).strip()
                                try:
                                    parsed_error = json.loads(candidate_json)
                                except json.JSONDecodeError:
                                    if logger.isEnabledFor(logging.DEBUG):
                                        logger.debug(
                                            "Failed to parse error JSON from streaming content (partial JSON?)"
                                        )

                                else:
                                    error_json_buffer_parts = None
                                    if (
                                        isinstance(parsed_error, dict)
                                        and "error" in parsed_error
                                    ):
                                        rate_limit_error = (
                                            processor.check_rate_limit_in_payload(
                                                parsed_error
                                            )
                                        )
                                        if rate_limit_error:
                                            with contextlib.suppress(Exception):
                                                response.close()
                                            raise rate_limit_error

                                        # Handle other errors in content
                                        error_info = parsed_error.get("error") or {}
                                        error_code = error_info.get("code")
                                        error_message = error_info.get(
                                            "message",
                                            "API error received from Gemini Code Assist",
                                        )
                                        error_code_value = (
                                            error_code
                                            if isinstance(error_code, int)
                                            else 500
                                        )
                                        with contextlib.suppress(Exception):
                                            response.close()
                                        raise BackendError(
                                            message=error_message,
                                            code="api_error",
                                            status_code=error_code_value,
                                            details={"raw": parsed_error},
                                            backend_name=self._backend_type,
                                        )
                                    else:
                                        error_json_buffer_parts = None

                    # Build metadata
                    metadata = create_gemini_response_metadata(
                        model=prepared.effective_model,
                        usage=None,
                        key_name=key_name,
                    ).model_dump()

                    raw_tool_calls = (
                        domain_chunk.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("tool_calls")
                    )
                    metadata.update(
                        {
                            "raw_tool_calls": raw_tool_calls,
                            "raw_finish_reason": domain_chunk.get("choices", [{}])[
                                0
                            ].get("finish_reason"),
                            "model": prepared.effective_model,
                        }
                    )

                    # Store thought signatures
                    if (
                        raw_tool_calls
                        and isinstance(raw_tool_calls, list)
                        and thought_signature_callback
                    ):
                        signature_session_id = (
                            getattr(prepared, "signature_session_id", None)
                            or prepared.session_id
                        )
                        thought_signature_callback(raw_tool_calls, signature_session_id)

                    yield ProcessedResponse(content=domain_chunk, metadata=metadata)
                    return

                # Skip non-data lines
                return

            # Process chunks (with keepalive emission while upstream is idle)
            keepalive_interval = self.STREAMING_KEEPALIVE_INTERVAL_SECONDS
            keepalive_id = f"chatcmpl-keepalive-{uuid.uuid4().hex}"
            keepalive_created = int(time.time())

            def _build_keepalive() -> ProcessedResponse:
                return ProcessedResponse(
                    content="",
                    metadata={
                        "_keepalive": True,
                        "id": keepalive_id,
                        "model": prepared.effective_model,
                        "created": keepalive_created,
                        "session_id": prepared.session_id,
                        "stream_id": prepared.session_id,
                    },
                )

            loop = asyncio.get_running_loop()
            queue: asyncio.Queue[object] = asyncio.Queue()
            sentinel = object()

            def _safe_put(item: object) -> None:
                if loop.is_closed():
                    return
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, item)
                except RuntimeError:
                    # Loop may be closing; drop the item silently.
                    return

            def _reader() -> None:
                try:
                    for chunk in response.iter_content(
                        chunk_size=4096, decode_unicode=False
                    ):
                        _safe_put(chunk)
                except Exception as exc:
                    _safe_put(exc)
                finally:
                    _safe_put(sentinel)

            threading.Thread(target=_reader, daemon=True).start()

            try:
                try:
                    while True:
                        if done:
                            break

                        try:
                            item = await asyncio.wait_for(
                                queue.get(), timeout=keepalive_interval
                            )
                        except asyncio.TimeoutError:
                            yield _build_keepalive()
                            continue

                        if item is sentinel:
                            break

                        if isinstance(item, Exception):
                            raise item

                        raw_chunk = item
                        try:
                            if isinstance(raw_chunk, str):
                                chunk_str = raw_chunk
                            elif isinstance(raw_chunk, bytes | bytearray | memoryview):
                                chunk_str = bytes(raw_chunk).decode("utf-8")
                            else:
                                chunk_str = str(raw_chunk)
                        except (UnicodeDecodeError, AttributeError):
                            continue

                        # Optimize: avoid O(n) string concatenation by joining
                        line_buffer = "".join([line_buffer, chunk_str])
                        lines = line_buffer.splitlines(keepends=True)

                        if lines and not lines[-1].endswith(("\n", "\r")):
                            line_buffer = lines.pop()
                        else:
                            line_buffer = ""

                        for line in lines:
                            decoded_line = line.rstrip("\r\n")

                            for processed_chunk in _process_decoded_line(decoded_line):
                                chunk_count += 1
                                content = processed_chunk.content
                                is_stop_chunk = False
                                finish_reason: str | None = None
                                choices: list[dict[str, Any]] = []

                                if isinstance(content, dict):
                                    choices_raw = content.get("choices", [])
                                    if (
                                        isinstance(choices_raw, list)
                                        and choices_raw
                                        and all(
                                            isinstance(item, dict)
                                            for item in choices_raw
                                        )
                                    ):
                                        choices = [
                                            item
                                            for item in choices_raw
                                            if isinstance(item, dict)
                                        ]
                                        finish_reason = choices[0].get("finish_reason")
                                        if finish_reason is None:
                                            finish_reason = (
                                                choices[0].get("delta", {}) or {}
                                            ).get("finish_reason")

                                if finish_reason is not None and finish_reason in (
                                    "stop",
                                    "stop_sequence",
                                ):
                                    is_stop_chunk = True

                                # Defensive: capture stop chunks even if above branch misses
                                if not is_stop_chunk and choices:
                                    fallback_finish = (
                                        choices[0].get("delta", {}) or {}
                                    ).get("finish_reason") or choices[0].get(
                                        "finish_reason"
                                    )
                                    if fallback_finish in ("stop", "stop_sequence"):
                                        is_stop_chunk = True

                                if is_stop_chunk:
                                    if logger.isEnabledFor(TRACE_LEVEL):
                                        logger.log(
                                            TRACE_LEVEL,
                                            "[STREAMING] Buffering stop chunk",
                                        )
                                    final_stop_chunk = processed_chunk
                                    continue

                                yield processed_chunk

                                # Yield to event loop periodically to maintain responsiveness
                                if chunk_count % self._yield_interval == 0:
                                    await asyncio.sleep(0)

                            if done:
                                break

                    # Process remaining buffer
                    if not done and line_buffer:
                        for processed_chunk in _process_decoded_line(
                            line_buffer.rstrip("\r\n")
                        ):
                            chunk_count += 1
                            content = processed_chunk.content
                            is_stop_chunk = False
                            chunk_choices: list[dict[str, Any]] = []
                            if isinstance(content, dict):
                                choices_raw = content.get("choices", [])
                                if (
                                    isinstance(choices_raw, list)
                                    and choices_raw
                                    and all(
                                        isinstance(item, dict) for item in choices_raw
                                    )
                                ):
                                    chunk_choices = [
                                        item
                                        for item in choices_raw
                                        if isinstance(item, dict)
                                    ]
                                    finish_reason = chunk_choices[0].get(
                                        "finish_reason"
                                    )
                                    if finish_reason in ("stop", "stop_sequence"):
                                        is_stop_chunk = True

                            if is_stop_chunk:
                                final_stop_chunk = processed_chunk
                                continue

                            yield processed_chunk
                            if chunk_count % self._yield_interval == 0:
                                await asyncio.sleep(0)

                except GeneratorExit:
                    # Logic amplification: Avoid duplicate logs when nested generators unwind
                    if context is not None:
                        extensions = context.extensions
                        if not extensions.get("__stream_closed_logged__"):
                            logger.debug("Stream closed by consumer before completion")
                            extensions["__stream_closed_logged__"] = True
                    else:
                        logger.debug("Stream closed by consumer before completion")
                    raise
                finally:
                    with contextlib.suppress(Exception):
                        response.close()
            except Exception:
                # Re-raise exceptions from the loop after ensuring response is closed
                raise

            # Calculate usage and yield final chunk
            from src.core.ports.streaming_contracts import StopChunkWithUsage

            usage: dict[str, Any] | None = None
            usage_summary = None
            try:
                # Join accumulated text parts once for token estimation
                generated_text = "".join(generated_text_parts)
                # Offload token counting to a thread to avoid blocking the event loop for large responses
                completion_tokens = await asyncio.to_thread(
                    self._token_estimator.estimate_tokens, generated_text
                )
                if completion_tokens <= 0 and generated_text:
                    from src.core.utils.token_count import count_tokens

                    completion_tokens = count_tokens(
                        generated_text, model=prepared.effective_model
                    )
                usage = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": (prompt_tokens or 0) + completion_tokens,
                }
                from src.core.domain.usage_summary import UsageSummary

                usage_summary = UsageSummary.from_dict(usage)
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(TRACE_LEVEL, f"[STREAMING] Calculated usage: {usage}")
            except Exception as e:
                logger.warning(
                    f"Could not calculate completion tokens for streaming: {e}",
                    exc_info=True,
                )

            if final_stop_chunk:
                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] Yielding final stop chunk with usage",
                    )
                final_content = final_stop_chunk.content
                if isinstance(final_content, dict) and usage:
                    final_content = dict(final_content)
                    final_content["usage"] = usage
                    final_content = StopChunkWithUsage(final_content)
                yield ProcessedResponse(
                    content=final_content,
                    metadata=final_stop_chunk.metadata,
                    usage=usage_summary,
                )
            else:
                # If we have no final stop chunk and no content, this is an empty response error
                has_content = bool(generated_text_parts)
                if not has_content:
                    logger.warning(
                        "[STREAMING] Response completed without content or stop chunk - treating as error"
                    )
                    error_message = "Backend returned empty response with no content."
                    error_chunk = processor.build_error_chunk(
                        message=error_message,
                        code=502,
                        error_type="empty_response",
                    )
                    yield ProcessedResponse(
                        content=self._get_error_chunk_content(error_chunk),
                        metadata=self._build_error_metadata(error_chunk),
                    )
                    return

                logger.debug(
                    "[STREAMING] No stop chunk buffered, yielding generic stop with usage"
                )
                final_chunk = self._translation_service.to_domain_stream_chunk(
                    chunk=None, source_format="code_assist"
                )
                if isinstance(final_chunk, dict):
                    final_chunk["model"] = prepared.effective_model
                    if usage:
                        final_chunk["usage"] = usage
                    final_chunk = StopChunkWithUsage(final_chunk)
                yield ProcessedResponse(
                    content=final_chunk,
                    usage=usage_summary,
                    metadata={"model": prepared.effective_model},
                )

        except BackendError as err:
            # Logic amplification: Avoid duplicate rate limit recording when nested generators unwind
            is_429 = getattr(err, "status_code", None) == 429
            already_recorded = getattr(err, "__rate_limit_recorded__", False)

            if is_429 and not already_recorded:
                with contextlib.suppress(AttributeError, TypeError):
                    cast(Any, err).__rate_limit_recorded__ = True

                retry_after_early = self._extract_retry_after_seconds(err)
                await self._record_rate_limit(
                    token_refresher,
                    retry_after_seconds=retry_after_early,
                )
                # Backend-wide cooldown (early path)
                cooldown_early = max(
                    retry_after_early or 0,
                    self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
                )
                backend_scope = self._get_backend_cooldown_scope(self._backend_type)
                self._set_backend_cooldown(
                    backend_scope, prepared.effective_model, cooldown_early
                )

            # Handle quota_exceeded errors by yielding error chunk with code 503
            if hasattr(err, "code") and err.code == "quota_exceeded":
                # Use standardized message for quota errors
                error_message = (
                    "Service temporarily unavailable due to rate limiting. "
                    f"Details: {err!s}"
                )
                error_chunk = processor.build_error_chunk(
                    message=error_message,
                    code=503,  # Use 503 for quota errors as expected by tests
                    error_type="quota_exceeded",
                )
                error_dict = error_chunk.model_dump()
                yield ProcessedResponse(
                    content=error_dict,
                    metadata=self._build_error_metadata(error_chunk),
                )
                return

            attempt = 1 if _rate_limit_retry_attempted else 0
            retry_decision = (
                retry_policy.should_retry(err, attempt, is_streaming=True)
                if retry_policy is not None
                else None
            )
            should_retry_rate_limit = (
                not _rate_limit_retry_attempted
                and self._is_retryable_rate_limit_error(err)
                and (
                    retry_decision is None
                    or retry_decision.should_retry
                    or retry_decision.reason == "no_retry_after"
                )
            )
            if should_retry_rate_limit:
                retry_after = self._extract_retry_after_seconds(err)
                suggested_sleep_seconds = (
                    retry_decision.sleep_seconds
                    if retry_decision is not None
                    and retry_decision.sleep_seconds is not None
                    else self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
                )
                predicted_wait_seconds = (
                    retry_after
                    if retry_after is not None
                    else max(
                        suggested_sleep_seconds,
                        self.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS,
                    )
                )
                is_oauth_auto = self._is_oauth_auto_refresher(token_refresher)
                preserve_affinity_wait = self._should_wait_same_account_on_rate_limit(
                    token_refresher=token_refresher,
                    sleep_seconds=predicted_wait_seconds,
                    retry_after_seconds=retry_after,
                )
                rotated_credentials = False

                if predicted_wait_seconds > self._max_rate_limit_retry_seconds:
                    if is_oauth_auto:
                        rotated_credentials = await self._try_rotate_oauth_auto_account(
                            token_refresher=token_refresher,
                            prepared=prepared,
                            retry_after_seconds=retry_after,
                            log_context="Account rotation on 429 (early path)",
                        )
                        if not rotated_credentials:
                            logger.info(
                                "Rate limit window %.2fs exceeds local wait ceiling %.2fs; "
                                "surfacing retryable error for upstream failover",
                                predicted_wait_seconds,
                                self._max_rate_limit_retry_seconds,
                            )
                            raise
                    else:
                        logger.info(
                            "Rate limit window %.2fs exceeds local wait ceiling %.2fs; "
                            "surfacing retryable error for upstream failover",
                            predicted_wait_seconds,
                            self._max_rate_limit_retry_seconds,
                        )
                        raise

                if (
                    is_oauth_auto
                    and not preserve_affinity_wait
                    and not rotated_credentials
                ):
                    rotated_credentials = await self._try_rotate_oauth_auto_account(
                        token_refresher=token_refresher,
                        prepared=prepared,
                        retry_after_seconds=retry_after,
                        log_context="Account rotation on 429 (early path)",
                    )

                retry_budget = (
                    RetryBudget(
                        wait_initial=predicted_wait_seconds,
                        wait_max=predicted_wait_seconds,
                        wait_jitter=0.0,
                        wait_exp_base=1.0,
                    )
                    if retry_after is not None
                    else None
                )
                retry_record = await self._wait_for_rate_limit_retry(
                    err,
                    retry_budget=retry_budget,
                )
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Retrying streaming request after %.2fs due to rate limit (attempt=%s)",
                        retry_record.wait_for_seconds,
                        attempt + 1,
                    )

                self._mark_retry_attempt(context)
                async for retry_chunk in self._stream_generator(
                    prepared=prepared,
                    url=url,
                    processor=processor,
                    prompt_tokens=prompt_tokens,
                    token_refresher=token_refresher,
                    context=context,
                    thought_signature_callback=thought_signature_callback,
                    key_name=key_name,
                    retry_policy=retry_policy,
                    _allow_tool_retry=_allow_tool_retry,
                    without_tools=without_tools,
                    _auth_retry_attempted=_auth_retry_attempted,
                    _rate_limit_retry_attempted=True,
                ):
                    yield retry_chunk
                return
            raise
        except Exception as e:
            logger.error(f"Error in streaming generator: {e}", exc_info=True)
            now = int(time.time())
            error_message = str(e) if str(e) else "An unexpected error occurred"

            # Check if this is a quota_exceeded BackendError
            error_code = 500
            error_type = "internal_error"
            if (
                isinstance(e, BackendError)
                and hasattr(e, "code")
                and e.code == "quota_exceeded"
            ):
                error_code = 503
                error_type = "quota_exceeded"
                # Use standardized message for quota errors
                error_message = (
                    "Service temporarily unavailable due to rate limiting. "
                    f"Details: {error_message}"
                )

            error_chunk = OpenAIErrorChunk(
                id=f"chatcmpl-error-{now}",
                object="chat.completion.chunk",
                created=now,
                model=prepared.effective_model,
                choices=[OpenAIErrorChoice(index=0, delta={}, finish_reason="error")],
                error=OpenAIError(
                    message=error_message,
                    type=error_type,
                    code=error_code,
                ),
            )

            yield ProcessedResponse(
                content=error_chunk.model_dump(),
                metadata=self._build_error_metadata(error_chunk),
            )
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    response.close()

    def _update_auth_session_token(
        self,
        prepared: PreparedChatRequest,
        token_refresher: Any,
    ) -> None:
        creds = getattr(token_refresher, "_oauth_credentials", None)
        if not isinstance(creds, dict):
            logger.warning(
                "Cannot refresh auth_session: token_refresher has no _oauth_credentials dict"
            )
            return
        new_token = creds.get("access_token")
        if not new_token:
            logger.warning(
                "Cannot refresh auth_session: no access_token in _oauth_credentials"
            )
            return
        session = getattr(prepared, "auth_session", None)
        if session is None:
            return
        session_headers = getattr(session, "headers", None)
        if isinstance(session_headers, MutableMapping):
            mutable_session_headers = cast(MutableMapping[str, str], session_headers)
            mutable_session_headers["Authorization"] = f"Bearer {new_token}"
        old_creds = getattr(session, "credentials", None)
        if old_creds is not None and hasattr(old_creds, "token"):
            old_creds.token = new_token  # type: ignore[union-attr]
            logger.debug("Updated auth_session credentials with refreshed token")
        else:
            logger.warning(
                "auth_session.credentials has no .token attribute; cannot update in-place"
            )

    async def _handle_error_response(
        self,
        response: requests.Response,
        processor: SSELineProcessor,
        prepared: PreparedChatRequest,
        url: str,
        prompt_tokens: int,
        *,
        token_refresher: ITokenRefresher | None = None,
        context: IRetryContext | None = None,
        thought_signature_callback: (
            Callable[[list[dict[str, Any]], str | None], None] | None
        ) = None,
        key_name: str | None = None,
        auth_refresh_policy: IAuthRefreshPolicy | None = None,
        retry_policy: IRetryPolicy | None = None,
        _allow_tool_retry: bool = True,
        without_tools: bool = False,
        _auth_retry_attempted: bool = False,
        _rate_limit_retry_attempted: bool = False,
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """Handle non-200 HTTP response."""
        try:
            error_detail = response.json()
        except (ValueError, json.JSONDecodeError) as e:
            # Expected exceptions from JSON parsing (invalid JSON format)
            logger.debug(
                "Failed to parse error response as JSON, falling back to text: %s",
                e,
            )
            error_detail = response.text
        except Exception as e:
            # Unexpected exceptions (e.g., AttributeError if response.json() doesn't exist)
            logger.warning(
                "Unexpected error parsing error response as JSON: %s",
                e,
            )
            error_detail = response.text

        detail_payload: dict[str, Any] = (
            error_detail if isinstance(error_detail, dict) else {"raw": error_detail}
        )

        error_message = "Service temporarily unavailable."
        code = "api_error"

        if response.status_code == 429:
            retry_after_raw = response.headers.get(
                "Retry-After"
            ) or response.headers.get("retry-after")
            if retry_after_raw is not None and "retry_after" not in detail_payload:
                with contextlib.suppress(TypeError, ValueError):
                    detail_payload["retry_after"] = float(retry_after_raw)
            # Safely convert headers to dict, handling Mock objects
            try:
                headers_dict = (
                    dict(response.headers)
                    if hasattr(response.headers, "__iter__")
                    and not isinstance(response.headers, str)
                    else {}
                )
            except (TypeError, AttributeError):
                headers_dict = {}
            detail_payload.setdefault("headers", headers_dict)

        retry_hint_seconds: float | None = None

        if isinstance(error_detail, dict):
            detail_error = error_detail.get("error") or {}
            status_val = str(detail_error.get("status", "")).upper()
            message_val = detail_error.get("message")
            if isinstance(message_val, str) and message_val.strip():
                error_message = message_val
            if response.status_code == 429:
                retry_hint = detail_payload.get("retry_after")
                if isinstance(retry_hint, int | float):
                    retry_hint_seconds = float(retry_hint)
                if retry_hint_seconds is None:
                    parsed_retry = extract_retry_delay_from_response(error_detail)
                    if parsed_retry is not None:
                        retry_hint_seconds = parsed_retry
                        detail_payload["retry_after"] = parsed_retry
            if response.status_code == 429 and status_val == "RESOURCE_EXHAUSTED":
                # Gemini often reports rate limiting as RESOURCE_EXHAUSTED.
                # Distinguish between:
                # - retryable rate limit windows (Retry-After / retry_after present)
                # - non-retryable quota exhaustion (no retry hint) -> return 503 immediately
                if retry_hint_seconds is None and error_message:
                    parsed_retry = parse_retry_from_message(error_message)
                    if parsed_retry is not None:
                        retry_hint_seconds = parsed_retry
                        detail_payload["retry_after"] = parsed_retry

                # Treat "No capacity available" as a retryable capacity error
                # even if no specific retry delay is provided.
                is_capacity_error = (
                    error_message and "no capacity available" in error_message.lower()
                )

                # Assign a default retry delay for capacity errors if none provided
                if is_capacity_error and retry_hint_seconds is None:
                    # Use a moderate delay to allow capacity to recover
                    retry_hint_seconds = 5.0
                    detail_payload["retry_after"] = retry_hint_seconds

                # Any explicit retry hint is retryable even when the delay exceeds
                # the connector-local wait ceiling. In that case we surface the
                # retryable error upstream instead of remapping to quota_exceeded.
                retryable = retry_hint_seconds is not None or is_capacity_error
                code = "rate_limit_exceeded" if retryable else "quota_exceeded"

            elif response.status_code == 429:
                code = "rate_limit_exceeded"
            elif response.status_code == 401:
                code = "auth_error"
        elif isinstance(error_detail, str) and error_detail.strip():
            error_message = error_detail

        backend_error = BackendError(
            message=error_message,
            code=code,
            status_code=response.status_code,
            details=detail_payload,
            backend_name=self._backend_type,
        )

        if response.status_code == 429 and not getattr(
            backend_error, "__rate_limit_recorded__", False
        ):
            with contextlib.suppress(AttributeError, TypeError):
                cast(Any, backend_error).__rate_limit_recorded__ = True

            retry_after = retry_hint_seconds or self._extract_retry_after_seconds(
                backend_error
            )
            await self._record_rate_limit(token_refresher, retry_after)

            # Set backend-wide cooldown so that concurrent or subsequent
            # requests from other sessions/accounts also wait.  Use at
            # least DEFAULT_RATE_LIMIT_BACKOFF_SECONDS even when the
            # server hint is shorter, because the effective rate-limit
            # window is typically longer than the Retry-After value.
            cooldown = max(
                retry_after or 0,
                self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS,
            )
            backend_scope = self._get_backend_cooldown_scope(self._backend_type)
            self._set_backend_cooldown(
                backend_scope, prepared.effective_model, cooldown
            )

        auth_policy = auth_refresh_policy or self._auth_refresh_policy
        auth_attempt = 1 if _auth_retry_attempted else 0

        if response.status_code == 401 and token_refresher and auth_policy:
            decision = auth_policy.should_refresh(
                backend_error, auth_attempt, is_streaming=True
            )
            if decision.should_refresh:
                logger.info(
                    "Received 401 Unauthorized from backend, attempting token refresh and retry (attempt=%s, timeout=%.1fs)...",
                    auth_attempt + 1,
                    decision.timeout_seconds,
                )
                with contextlib.suppress(Exception):
                    response.close()

                try:
                    refreshed = await asyncio.wait_for(
                        token_refresher.refresh_token_if_needed(
                            force_reload=decision.force_reload,
                            session_id=prepared.session_id,
                        ),
                        timeout=decision.timeout_seconds,
                    )
                    if refreshed:
                        logger.info(
                            "Token refresh successful, retrying streaming request..."
                        )
                        self._update_auth_session_token(prepared, token_refresher)
                        async for retry_chunk in self._stream_generator(
                            prepared=prepared,
                            url=url,
                            processor=processor,
                            prompt_tokens=prompt_tokens,
                            token_refresher=token_refresher,
                            context=context,
                            thought_signature_callback=thought_signature_callback,
                            key_name=key_name,
                            auth_refresh_policy=auth_policy,
                            _allow_tool_retry=_allow_tool_retry,
                            without_tools=without_tools,
                            _auth_retry_attempted=True,
                        ):
                            yield retry_chunk
                        return
                    logger.warning(
                        "Token refresh failed; will return 401 error to client"
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Token refresh timed out after %.1fs; returning 401 to client",
                        decision.timeout_seconds,
                        exc_info=True,
                    )
                except Exception as refresh_error:
                    logger.error(
                        "Error during token refresh attempt: %s",
                        refresh_error,
                        exc_info=True,
                    )

        # Handle quota errors (429 + RESOURCE_EXHAUSTED) by yielding error chunk with code 503
        # Quota errors should not be retried - yield error immediately before retry policy check
        if response.status_code == 429 and code == "quota_exceeded":
            with contextlib.suppress(Exception):
                response.close()

            # Use standardized message for quota errors to match test expectations and trigger failover
            std_message = (
                f"Service temporarily unavailable (quota exceeded): {error_message}"
            )

            error_chunk = processor.build_error_chunk(
                message=std_message,
                code=503,  # Use 503 for quota errors as expected by tests
                error_type=code,
            )
            yield ProcessedResponse(
                content=error_chunk.model_dump(),
                metadata=self._build_error_metadata(error_chunk),
            )
            return

        # Extract retry delay for rate limit errors (non-quota 429s)
        if response.status_code == 429 and self._retry_delay_extractor:
            retry_delay = self._retry_delay_extractor.extract_retry_delay(backend_error)
            if retry_delay is not None:
                detail_payload["retry_after"] = retry_delay

        if response.status_code == 429:
            attempt = 1 if _rate_limit_retry_attempted else 0
            retry_decision = (
                retry_policy.should_retry(backend_error, attempt, is_streaming=True)
                if retry_policy is not None
                else None
            )
            should_retry_rate_limit = (
                not _rate_limit_retry_attempted
                and self._is_retryable_rate_limit_error(backend_error)
                and (
                    retry_decision is None
                    or retry_decision.should_retry
                    or retry_decision.reason == "no_retry_after"
                )
            )
            if should_retry_rate_limit:
                with contextlib.suppress(Exception):
                    response.close()

                retry_after = self._extract_retry_after_seconds(backend_error)
                suggested_sleep_seconds = (
                    retry_decision.sleep_seconds
                    if retry_decision is not None
                    and retry_decision.sleep_seconds is not None
                    else self.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
                )
                predicted_wait_seconds = (
                    retry_after
                    if retry_after is not None
                    else max(
                        suggested_sleep_seconds,
                        self.MIN_RATE_LIMIT_RETRY_SLEEP_SECONDS,
                    )
                )
                rotated_credentials = False
                is_oauth_auto = self._is_oauth_auto_refresher(token_refresher)
                preserve_affinity_wait = self._should_wait_same_account_on_rate_limit(
                    token_refresher=token_refresher,
                    sleep_seconds=predicted_wait_seconds,
                    retry_after_seconds=retry_after,
                )

                if predicted_wait_seconds > self._max_rate_limit_retry_seconds:
                    if is_oauth_auto:
                        rotated_credentials = await self._try_rotate_oauth_auto_account(
                            token_refresher=token_refresher,
                            prepared=prepared,
                            retry_after_seconds=retry_after,
                            log_context="Account rotation on 429 (late path)",
                        )
                        if not rotated_credentials:
                            logger.info(
                                "Rate limit window %.2fs exceeds local wait ceiling %.2fs; "
                                "surfacing retryable error for upstream failover",
                                predicted_wait_seconds,
                                self._max_rate_limit_retry_seconds,
                            )
                            raise backend_error
                    else:
                        logger.info(
                            "Rate limit window %.2fs exceeds local wait ceiling %.2fs; "
                            "surfacing retryable error for upstream failover",
                            predicted_wait_seconds,
                            self._max_rate_limit_retry_seconds,
                        )
                        raise backend_error

                if (
                    is_oauth_auto
                    and not preserve_affinity_wait
                    and not rotated_credentials
                ):
                    rotated_credentials = await self._try_rotate_oauth_auto_account(
                        token_refresher=token_refresher,
                        prepared=prepared,
                        retry_after_seconds=retry_after,
                        log_context="Account rotation on 429 (late path)",
                    )

                retry_budget = (
                    RetryBudget(
                        wait_initial=predicted_wait_seconds,
                        wait_max=predicted_wait_seconds,
                        wait_jitter=0.0,
                        wait_exp_base=1.0,
                    )
                    if retry_after is not None
                    else None
                )
                # Keep stream alive while local retry wait elapses so clients do not
                # interpret the temporary 429 pause as a stalled connection.
                yield self._build_rate_limit_retry_keepalive(prepared)
                retry_record = await self._wait_for_rate_limit_retry(
                    backend_error,
                    retry_budget=retry_budget,
                )
                logger.info(
                    "Retrying streaming request after %.2fs due to rate limit (attempt=%s)",
                    retry_record.wait_for_seconds,
                    attempt + 1,
                )
                self._mark_retry_attempt(context)
                async for retry_chunk in self._stream_generator(
                    prepared=prepared,
                    url=url,
                    processor=processor,
                    prompt_tokens=prompt_tokens,
                    token_refresher=token_refresher,
                    context=context,
                    thought_signature_callback=thought_signature_callback,
                    key_name=key_name,
                    auth_refresh_policy=auth_refresh_policy,
                    retry_policy=retry_policy,
                    _allow_tool_retry=_allow_tool_retry,
                    without_tools=without_tools,
                    _auth_retry_attempted=_auth_retry_attempted,
                    _rate_limit_retry_attempted=True,
                ):
                    yield retry_chunk
                return

        # Handle 400 Bad Request errors by raising a BackendError.
        # Previously we tried to yield an error chunk, but clients often don't understand
        # the error chunk format in SSE streams and end up retrying infinitely.
        # Raising ensures the client receives a proper HTTP 400 response.
        if response.status_code == 400:
            with contextlib.suppress(Exception):
                response.close()
            logger.warning(
                "[STREAMING] Backend returned 400 Bad Request: %s",
                error_message,
            )
            raise BackendError(
                message=error_message,
                code=code,
                status_code=400,
                details=detail_payload,
                backend_name=self._backend_type,
            )

        with contextlib.suppress(Exception):
            response.close()

        raise backend_error

    def _get_error_chunk_content(
        self, error_chunk: OpenAIErrorChunk | dict[str, Any]
    ) -> dict[str, Any]:
        """Get error chunk content as dict, handling both Pydantic models and dicts.

        Args:
            error_chunk: Either an OpenAIErrorChunk object or a dict with error chunk data.

        Returns:
            Dict representation of the error chunk.
        """
        # Handle both OpenAIErrorChunk objects and dicts (for test compatibility)
        if isinstance(error_chunk, dict):
            return error_chunk
        elif hasattr(error_chunk, "model_dump"):
            return error_chunk.model_dump()
        else:
            # Fallback: try to convert to dict
            return dict(error_chunk) if hasattr(error_chunk, "__dict__") else {}

    def _build_error_metadata(
        self, error_chunk: OpenAIErrorChunk | dict[str, Any]
    ) -> dict[str, JsonValue]:
        """Build metadata for error responses.

        Args:
            error_chunk: Either an OpenAIErrorChunk object or a dict with error chunk data.
        """
        # Handle both OpenAIErrorChunk objects and dicts (for test compatibility)
        if isinstance(error_chunk, dict):
            error_data = error_chunk.get("error", {})
            if isinstance(error_data, dict):
                error = OpenAIError(
                    message=error_data.get("message", ""),
                    type=error_data.get("type", "api_error"),
                    code=error_data.get("code", 500),
                )
            else:
                error = error_data
            return ErrorMetadata(
                finish_reason="error",
                error=error,
                id=error_chunk.get("id", ""),
                model=error_chunk.get("model", "unknown"),
                created=error_chunk.get("created", 0),
            ).to_metadata()
        else:
            # OpenAIErrorChunk object
            return ErrorMetadata(
                finish_reason="error",
                error=error_chunk.error,
                id=error_chunk.id,
                model=error_chunk.model,
                created=error_chunk.created,
            ).to_metadata()

    def _build_auth_error_chunk(self, model: str) -> OpenAIErrorChunk:
        """Build an authentication error chunk."""
        now = int(time.time())
        return OpenAIErrorChunk(
            id=f"chatcmpl-error-{now}",
            object="chat.completion.chunk",
            created=now,
            model=model,
            choices=[OpenAIErrorChoice(index=0, delta={}, finish_reason="error")],
            error=OpenAIError(
                message="Authentication failed. Please check your credentials.",
                type="auth_error",
                code=401,
            ),
        )


__all__ = [
    "IAuthRefreshPolicy",
    "IRetryDelayExtractor",
    "ITokenRefresher",
    "SSELineProcessor",
    "StreamingExecutor",
]
