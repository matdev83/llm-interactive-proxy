"""
Base class for Gemini OAuth connectors.
"""

import abc
import asyncio
import contextlib
import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Iterable
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
import requests  # type: ignore[import-untyped]
from fastapi import HTTPException

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
)

if TYPE_CHECKING:
    import subprocess

    from watchdog.observers.api import BaseObserver

from src.connectors.gemini import GeminiBackend
from src.connectors.gemini_base.config import (
    CODE_ASSIST_ENDPOINT,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    DEFAULT_READ_TIMEOUT,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.connectors.gemini_base.credential_loader import CredentialLoader
from src.connectors.gemini_base.credentials import (
    TOKEN_EXPIRY_BUFFER_SECONDS,
    _StaticTokenCreds,
)
from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState
from src.connectors.gemini_base.graceful_degradation import (
    calculate_retry_delay,
    get_fallback_model,
    is_model_in_cooldown,
    is_rate_limit_like_error,
    set_model_cooldown,
)
from src.connectors.gemini_base.prompt_limiter import (
    enforce_prompt_limit,
    estimate_prompt_tokens,
    get_prompt_limit,
    normalize_model_key,
)
from src.connectors.gemini_base.token_manager import TokenManager
from src.connectors.gemini_base.tool_sanitizer import sanitize_code_assist_tools
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin
from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.gemini_metadata import (
    create_gemini_generation_config,
    create_gemini_response_metadata,
)
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import LOOP_GUARD_HEADER, LOOP_GUARD_VALUE
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)


def _get_google_transport_requests():
    """Lazily import google.auth transport to avoid heavy startup cost."""

    import google.auth.transport.requests as transport_requests  # type: ignore[import-untyped]

    return transport_requests


def _get_google_auth_exceptions():
    """Lazily import google.auth exceptions."""

    import google.auth.exceptions as google_auth_exceptions  # type: ignore[import-untyped]

    return google_auth_exceptions


@lru_cache(maxsize=1)
def _get_tiktoken_encoding():
    """Return cached tiktoken encoding instance."""

    import tiktoken  # type: ignore[import-untyped]

    return tiktoken.get_encoding("cl100k_base")


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

    _project_id: str | None = None

    # Server-side storage for Gemini thought_signatures.
    # Droid and similar clients don't preserve extra_content, so we store
    # the mapping of tool_call_id -> thought_signature server-side and
    # inject it when processing subsequent requests.
    # Key format: "session_id:tool_call_id" -> thought_signature
    _thought_signature_cache: dict[str, str] = {}

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

    @classmethod
    def _inject_thought_signatures(
        cls, canonical_request: Any, session_id: str
    ) -> None:
        """Inject stored thought_signatures into tool_calls that are missing them.

        Clients like Droid don't preserve extra_content when storing tool calls,
        so we need to look up and inject the thought_signature from our server-side cache.

        Args:
            canonical_request: The canonical request with messages to process
            session_id: The session ID for cache key lookup
        """
        if not hasattr(canonical_request, "messages"):
            return

        for message in canonical_request.messages:
            if getattr(message, "role", None) != "assistant":
                continue
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                continue

            for tc in tool_calls:
                # Get tool call ID
                tc_id = None
                if isinstance(tc, dict):
                    tc_id = tc.get("id")
                elif hasattr(tc, "id"):
                    tc_id = tc.id

                if not tc_id:
                    continue

                # Check if already has thought_signature
                extra_content = None
                if isinstance(tc, dict):
                    extra_content = tc.get("extra_content")
                elif hasattr(tc, "extra_content"):
                    extra_content = tc.extra_content

                if extra_content:
                    google_extra = (
                        extra_content.get("google", {})
                        if isinstance(extra_content, dict)
                        else {}
                    )
                    if google_extra.get("thought_signature"):
                        continue  # Already has signature

                # Look up in cache
                cache_key = f"{session_id}:{tc_id}"
                sig = cls._thought_signature_cache.get(cache_key)
                if sig:
                    # Inject the signature
                    if isinstance(tc, dict):
                        tc["extra_content"] = {"google": {"thought_signature": sig}}
                    elif hasattr(tc, "extra_content"):
                        tc.extra_content = {"google": {"thought_signature": sig}}
                    logger.debug(
                        "Injected thought_signature for tool_call_id=%s (session=%s)",
                        tc_id,
                        session_id[:8] if session_id else "none",
                    )

    @staticmethod
    def _extract_generated_text_from_response(response_payload: Any) -> str:
        """Extract concatenated text content from a Gemini Code Assist response."""

        def _detect_rate_limit(details: dict[str, Any]) -> bool:
            error = details.get("error")
            if isinstance(error, dict):
                error_code = error.get("code")
                if isinstance(error_code, int) and error_code == 429:
                    return True
                message = error.get("message")
                if isinstance(message, str):
                    lower = message.lower()
                    if any(
                        phrase in lower
                        for phrase in (
                            "resource exhausted",
                            "rate limit",
                            "quota",
                            "too many requests",
                        )
                    ):
                        return True
            message = details.get("message")
            if isinstance(message, str):
                lower = message.lower()
                if any(
                    phrase in lower
                    for phrase in (
                        "resource exhausted",
                        "rate limit",
                        "quota",
                        "too many requests",
                    )
                ):
                    return True
            return False

        def _build_preview(payload: Any) -> str:
            try:
                text = json.dumps(payload, ensure_ascii=False)  # type: ignore[arg-type]
            except Exception:
                text = repr(payload)
            if len(text) > 512:
                return text[:512] + "…"
            return text

        def _log_anomaly(message: str, payload: Any | None = None) -> None:
            if not logger.isEnabledFor(logging.WARNING):
                return
            extra: dict[str, Any] = {
                "event": "gemini_response_anomaly",
                "log_message": message,
            }
            formatted_message = message
            if payload is not None:
                preview = _build_preview(payload)
                extra["payload_preview"] = preview
                formatted_message = f"{message}; payload_preview={preview}"
            logger.warning(formatted_message, extra=extra)

        def _raise_error(
            message: str,
            code: str,
            details: dict[str, Any],
            *,
            default_status: int = 503,
            payload: Any | None = None,
        ) -> None:
            status_code = 429 if _detect_rate_limit(details) else default_status
            if payload is not None:
                details = {**details, "payload_preview": _build_preview(payload)}
            raise BackendError(
                message=message,
                code=code,
                details=details,
                status_code=status_code,
            )

        candidate_dicts: list[dict[str, Any]] = []
        visited: set[int] = set()

        def _walk(node: Any) -> None:
            if isinstance(node, str | bytes | int | float | bool) or node is None:
                return

            node_id = id(node)
            if node_id in visited:
                return
            visited.add(node_id)

            if isinstance(node, dict):
                error_obj = node.get("error")
                if isinstance(error_obj, dict):
                    _log_anomaly("Gemini API returned error object", node)
                    _raise_error(
                        "Gemini API returned an error payload",
                        "gemini_error_payload",
                        {"error": error_obj},
                        payload=response_payload,
                    )

                maybe_candidates = node.get("candidates")
                if isinstance(maybe_candidates, list) and maybe_candidates:
                    candidate_dicts.extend(
                        candidate
                        for candidate in maybe_candidates
                        if isinstance(candidate, dict)
                    )

                for value in node.values():
                    _walk(value)

            elif isinstance(node, list | tuple):
                for item in node:
                    _walk(item)
            else:
                # Unsupported container type
                return

        if isinstance(response_payload, dict | list | tuple):
            _walk(response_payload)
        else:
            _raise_error(
                f"Unexpected response format: {type(response_payload).__name__}",
                "unexpected_response_format",
                {"payload_type": type(response_payload).__name__},
                default_status=502,
                payload=response_payload,
            )

        if not candidate_dicts:
            payload_type = (
                type(response_payload).__name__
                if not isinstance(response_payload, list)
                else "list"
            )
            _log_anomaly(
                "Gemini response contained no candidates",
                response_payload,
            )
            _raise_error(
                "Gemini response did not include any candidates",
                "empty_response",
                {"payload_type": payload_type},
                default_status=502,
                payload=response_payload,
            )

        text_parts: list[str] = []
        for candidate in candidate_dicts:
            if not isinstance(candidate, dict):
                continue
            candidate_error = candidate.get("error")
            if isinstance(candidate_error, dict):
                _raise_error(
                    "Gemini candidate contained an error payload",
                    "gemini_error_payload",
                    {"error": candidate_error},
                )
            content = candidate.get("content", {})
            if not isinstance(content, dict):
                continue
            parts = content.get("parts", [])
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text_value = part.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)

        if not text_parts or not any(part.strip() for part in text_parts):
            logger.warning(
                "List response from Gemini API contained no candidates. This may be due to safety settings or other content filters."
            )
            _log_anomaly(
                "Gemini response list contained no text parts",
                response_payload,
            )
            _raise_error(
                "Gemini response did not contain any text content",
                "empty_response",
                {"payload_type": type(response_payload).__name__},
                default_status=502,
                payload=response_payload,
            )

        return "".join(text_parts)

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        name: str,
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

        # Token management (composed)
        self._token_manager = TokenManager()
        # File watching (composed)
        self._file_watcher_state = FileWatcherState()
        # Store reference to the main event loop for thread-safe operations
        self._main_loop: asyncio.AbstractEventLoop | None = None
        # Flag to track if quota has been exceeded
        self._quota_exceeded = False
        self._request_counter: DailyRequestCounter | None = None

        # Health checks are enabled by default and controlled by the AppConfig
        self._health_checked: bool = not self.config.get("disable_health_checks", False)

        # Set custom .gemini directory path (will be set in initialize)
        self.gemini_cli_oauth_path: str | None = None
        self._request_counter = DailyRequestCounter(
            persistence_path=Path("data/gemini_oauth_request_count.json"), limit=1000
        )

        # Initialize graceful degradation
        self._graceful_metrics = GracefulDegradationMetrics()
        self._degradation_config = GracefulDegradationConfig.from_config(self.config)
        self._model_retry_states: dict[str, ModelRetryState] = {}
        self._permanently_failed = False
        self._recovery_probe_task: asyncio.Task[Any] | None = None

        # Cache for fast model validation lookups
        self._available_models_set: set[str] = set()
        # Flag to track if models were loaded from API (vs hardcoded fallback)
        self._models_from_api: bool = False

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

    # Backward-compatible properties for TokenManager internals
    @property
    def _refresh_token(self) -> str | None:
        """Backward-compatible access to cached refresh token."""
        return self._token_manager._refresh_token

    @_refresh_token.setter
    def _refresh_token(self, value: str | None) -> None:
        """Backward-compatible setter for refresh token."""
        self._token_manager._refresh_token = value

    @property
    def _cli_refresh_process(self) -> "subprocess.Popen[bytes] | None":
        """Backward-compatible access to CLI refresh subprocess."""
        return self._token_manager._cli_refresh_process

    @_cli_refresh_process.setter
    def _cli_refresh_process(self, value: "subprocess.Popen[bytes] | None") -> None:
        """Backward-compatible setter for CLI refresh subprocess."""
        self._token_manager._cli_refresh_process = value

    @property
    def _last_cli_refresh_attempt(self) -> float:
        """Backward-compatible access to last CLI refresh timestamp."""
        return self._token_manager._last_cli_refresh_attempt

    @_last_cli_refresh_attempt.setter
    def _last_cli_refresh_attempt(self, value: float) -> None:
        """Backward-compatible setter for last CLI refresh timestamp."""
        self._token_manager._last_cli_refresh_attempt = value

    @property
    def _token_refresh_lock(self) -> "asyncio.Lock":
        """Backward-compatible access to token refresh lock."""
        return self._token_manager._token_refresh_lock

    # Backward-compatible properties for FileWatcherState internals
    @property
    def _file_observer(self) -> "BaseObserver | None":
        """Backward-compatible access to file observer."""
        return self._file_watcher_state.file_observer

    @_file_observer.setter
    def _file_observer(self, value: "BaseObserver | None") -> None:
        """Backward-compatible setter for file observer."""
        self._file_watcher_state.file_observer = value

    @property
    def _pending_reload_task(self) -> asyncio.Future[Any] | None:
        """Backward-compatible access to pending reload task."""
        return self._file_watcher_state.pending_reload_task

    @_pending_reload_task.setter
    def _pending_reload_task(self, value: asyncio.Future[Any] | None) -> None:
        """Backward-compatible setter for pending reload task."""
        self._file_watcher_state.pending_reload_task = value

    @property
    def _reload_task_lock(self) -> threading.Lock:
        """Backward-compatible access to reload task lock."""
        return self._file_watcher_state.reload_task_lock

    @property
    def _reload_scheduling_in_progress(self) -> bool:
        """Backward-compatible access to reload scheduling flag."""
        return self._file_watcher_state.reload_scheduling_in_progress

    @_reload_scheduling_in_progress.setter
    def _reload_scheduling_in_progress(self, value: bool) -> None:
        """Backward-compatible setter for reload scheduling flag."""
        self._file_watcher_state.reload_scheduling_in_progress = value

    @property
    def _last_reload_event_ts(self) -> float:
        """Backward-compatible access to last reload event timestamp."""
        return self._file_watcher_state.last_reload_event_ts

    @_last_reload_event_ts.setter
    def _last_reload_event_ts(self, value: float) -> None:
        """Backward-compatible setter for last reload event timestamp."""
        self._file_watcher_state.last_reload_event_ts = value

    def get_graceful_degradation_metrics(self) -> dict[str, float | int]:
        """Expose graceful degradation telemetry for diagnostics."""
        return self._graceful_metrics.as_dict()

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
        """Best-effort estimate of prompt token usage for the current request."""
        encoding = _get_tiktoken_encoding()
        return estimate_prompt_tokens(code_assist_request, encoding)

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

    async def _refresh_token_if_needed(self) -> bool:
        """Ensure a valid access token is available, refreshing when necessary."""
        return await self._token_manager.refresh_token_if_needed(self)

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

        Subclasses can override this to add custom headers (e.g., User-Agent).
        """
        headers: dict[str, str] = {}
        if self._oauth_credentials and self._oauth_credentials.get("access_token"):
            headers["Authorization"] = (
                f"Bearer {self._oauth_credentials['access_token']}"
            )
        headers["Content-Type"] = "application/json"
        return headers

    def _get_session_headers(self) -> dict[str, str]:
        """
        Get headers for AuthorizedSession requests (used with requests library).

        Subclasses can override this to add custom headers (e.g., User-Agent).
        These headers are applied to the google.auth AuthorizedSession used for
        API calls like streamGenerateContent.
        """
        return {}

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
            # Use the effective model (strip gemini-oauth-plan: prefix if present)
            model_name = effective_model
            prefix = "gemini-oauth-plan:"
            if model_name.startswith(prefix):
                model_name = model_name[len(prefix) :]

            # Check if streaming is requested
            is_streaming = getattr(request_data, "stream", False)

            try:
                if is_streaming:
                    return await self._chat_completions_code_assist_streaming(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model_name,
                        **kwargs,
                    )
                else:
                    return await self._chat_completions_code_assist(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model_name,
                        **kwargs,
                    )
            except BackendError as e:
                # Handle 429 errors with graceful degradation
                if getattr(e, "status_code", None) == 429:
                    if self._degradation_config.enabled:
                        return await self._handle_429_with_graceful_degradation(
                            original_model=model_name,
                            request_data=request_data,
                            processed_messages=processed_messages,
                            error=e,
                            **kwargs,
                        )
                    else:
                        # Graceful degradation disabled, use original behavior
                        self._quota_exceeded = True
                        self.is_functional = False
                        logger.error(
                            "Backend %s marked as unusable due to rate limit and graceful degradation disabled. "
                            "Manual intervention may be required to restore functionality.",
                            self.name,
                        )
                        raise
                else:
                    # Re-raise non-429 BackendErrors
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

        This method builds the wrapper structure around the inner code_assist_request.
        Subclasses can override this to customize the request body format
        (e.g., Antigravity uses a different wrapper structure).

        Args:
            effective_model: The model name to use
            project_id: The project ID from loadCodeAssist
            request_data: The original request data (for generating user_prompt_id)
            code_assist_request: The inner request with contents, generationConfig, etc.

        Returns:
            Complete request body dict ready to send to the API
        """
        return {
            "model": effective_model,
            "project": project_id,
            "user_prompt_id": self._generate_user_prompt_id(request_data),
            "request": code_assist_request,
        }

    @staticmethod
    def _sanitize_code_assist_tools(
        canonical_request: Any, code_assist_request: dict[str, Any]
    ) -> None:
        """Ensure only Gemini-compatible function tools are sent."""
        sanitize_code_assist_tools(canonical_request, code_assist_request)

    async def _chat_completions_code_assist(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _in_graceful_degradation: bool = False,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle chat completions using the Code Assist API.

        This method implements the Code Assist API calls that match the Gemini CLI
        approach, while converting to/from OpenAI-compatible formats.
        """
        try:
            # Ensure token is refreshed before making the API call
            if not await self._refresh_token_if_needed():
                raise AuthenticationError("Failed to refresh OAuth token for API call")

            if self._request_counter:
                self._request_counter.increment()

            # Create an authorized session using the access token directly
            if not self._oauth_credentials:
                raise AuthenticationError("No OAuth credentials available for API call")

            access_token = self._oauth_credentials.get("access_token")
            if not access_token:
                raise AuthenticationError("Missing access_token in OAuth credentials")

            # Build a simple authorized session wrapper using Requests
            # We use AuthorizedSession with a bare Credentials-like shim
            transport_requests = _get_google_transport_requests()
            auth_session = transport_requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )
            auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)
            # Apply custom headers (e.g., User-Agent for Antigravity)
            for key, value in self._get_session_headers().items():
                auth_session.headers[key] = value

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

            # Debug logging to trace message flow
            if logger.isEnabledFor(logging.DEBUG):
                message_count = (
                    len(canonical_request.messages)
                    if hasattr(canonical_request, "messages")
                    else 0
                )
                logger.debug(
                    f"Processing {message_count} messages for Gemini Code Assist API"
                )
                if message_count > 0 and hasattr(canonical_request, "messages"):
                    last_msg = canonical_request.messages[-1]
                    logger.debug(
                        f"Last message role={getattr(last_msg, 'role', 'unknown')}, content length={len(str(getattr(last_msg, 'content', '')))}"
                    )

            # Inject stored thought_signatures for clients that don't preserve extra_content
            session_id = getattr(request_data, "session_id", None) or ""
            self._inject_thought_signatures(canonical_request, session_id)

            # Convert from canonical/domain format to Gemini API format
            gemini_request = self.translation_service.from_domain_to_gemini_request(
                canonical_request
            )

            # Use mixin method to convert system messages (KiloCode's approach)
            # This avoids the 64K token limit on the separate systemInstruction field
            final_contents = self._convert_system_messages_for_code_assist(
                gemini_request
            )

            # Use mixin method to build Code Assist API request
            code_assist_request = self._build_code_assist_request(
                gemini_request, final_contents
            )

            # Strip/repair unsupported tool definitions (e.g., custom tools from clients)
            self._sanitize_code_assist_tools(canonical_request, code_assist_request)

            prompt_tokens_estimate = self._estimate_prompt_tokens(code_assist_request)
            self._enforce_prompt_limit(
                prompt_tokens_estimate,
                effective_model,
                request_id=getattr(request_data, "id", None),
            )

            # Prepare request body for Code Assist API
            # Using hook method to allow subclasses to customize the wrapper format
            def _build_request_body() -> dict[str, Any]:
                return self._build_code_assist_request_body(
                    effective_model=effective_model,
                    project_id=project_id,
                    request_data=request_data,
                    code_assist_request=code_assist_request,
                )

            # Log request details for debugging token issues
            if logger.isEnabledFor(logging.DEBUG):
                first_msg_size = 0
                contents_list = code_assist_request.get("contents", [])
                if contents_list and len(contents_list) > 0:
                    first_msg_parts = contents_list[0].get("parts", [])
                    for part in first_msg_parts:
                        if "text" in part:
                            first_msg_size += len(part["text"])
                logger.debug(
                    f"Code Assist request: first message size={first_msg_size} chars, "
                    f"contents count={len(contents_list)}, "
                    f"estimated tokens={prompt_tokens_estimate}"
                )

            # Use the Code Assist API exactly like KiloCode does
            # IMPORTANT: KiloCode uses :streamGenerateContent, not :generateContent
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making Code Assist API call to: {url}")

            # Build the request body (must be called after sanitization)
            request_body = _build_request_body()

            # Make the actual API call
            try:
                response = await asyncio.to_thread(
                    auth_session.request,
                    method="POST",
                    url=url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=int(DEFAULT_READ_TIMEOUT),
                )
            except requests.exceptions.Timeout as te:
                logger.error(f"Timeout calling {url}: {te}", exc_info=True)
                raise BackendError(f"Request timeout: {te}")
            except requests.exceptions.RequestException as rexc:
                logger.error(f"Connection error calling {url}: {rexc}", exc_info=True)
                raise BackendError(f"Connection failed: {rexc}")

            if response.status_code >= 400:
                self._handle_streaming_error(response)

            # Extract and process the response
            try:
                response_json = response.json()
                openai_response = self._extract_generated_text_from_response(
                    response_json
                )
            except BackendError:
                # Preserve backend-specific error codes/details for graceful handling
                raise
            except Exception as e:
                message = f"Failed to process API response: {e}"
                logger.error(message, exc_info=True)
                raise BackendError(
                    message=message,
                    backend_name=self.backend_type,
                    code="gemini_response_processing_failed",
                    details={"inner_error": str(e)},
                ) from e

            # Calculate usage (best effort)
            encoding = _get_tiktoken_encoding()
            prompt_tokens_estimate = self._estimate_prompt_tokens(code_assist_request)
            completion_tokens = len(encoding.encode(openai_response))
            usage = {
                "prompt_tokens": prompt_tokens_estimate or 0,
                "completion_tokens": completion_tokens,
                "total_tokens": (prompt_tokens_estimate or 0) + completion_tokens,
            }

            logger.info(
                "Successfully received and processed response from Code Assist API"
            )
            return ResponseEnvelope(
                content=openai_response, headers={}, status_code=200, usage=usage
            )

        except AuthenticationError as e:
            logger.error(f"Authentication error during API call: {e}", exc_info=True)
            raise
        except BackendError as e:
            if self._is_rate_limit_like_error(e):
                logger.info("Backend rate limited during API call: %s", e)
            else:
                logger.error(f"Backend error during API call: {e}", exc_info=True)
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
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions using the Code Assist API.

        This method implements proper streaming support for the Code Assist API,
        returning a StreamingResponseEnvelope that provides an async iterator
        of SSE-formatted response chunks.
        """

        from src.core.ports.streaming_contracts import handle_streaming_error

        try:
            # Ensure token is refreshed before making the API call
            if not await self._refresh_token_if_needed():
                raise AuthenticationError(
                    "Failed to refresh OAuth token for streaming API call"
                )

            if self._request_counter:
                self._request_counter.increment()

            # Create an authorized session using the access token directly
            if not self._oauth_credentials:
                raise AuthenticationError(
                    "No OAuth credentials available for streaming API call"
                )

            access_token = self._oauth_credentials.get("access_token")
            if not access_token:
                raise AuthenticationError("Missing access_token in OAuth credentials")

            transport_requests = _get_google_transport_requests()
            auth_session = transport_requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )
            auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)
            # Apply custom headers (e.g., User-Agent for Antigravity)
            for key, value in self._get_session_headers().items():
                auth_session.headers[key] = value

            # Discover project ID (required for Code Assist API)
            project_id = await self._discover_project_id(auth_session)

            # request_data is expected to be a CanonicalChatRequest already
            # (the frontend controller converts from frontend-specific format to domain format)
            # Backends should ONLY convert FROM domain TO backend-specific format
            canonical_request = request_data

            # Debug logging to trace message flow (streaming)
            if logger.isEnabledFor(logging.DEBUG):
                message_count = (
                    len(canonical_request.messages)
                    if hasattr(canonical_request, "messages")
                    else 0
                )
                logger.debug(
                    f"[STREAMING] Processing {message_count} messages for Gemini Code Assist API"
                )
                if message_count > 0 and hasattr(canonical_request, "messages"):
                    last_msg = canonical_request.messages[-1]
                    logger.debug(
                        f"[STREAMING] Last message role={getattr(last_msg, 'role', 'unknown')}, content length={len(str(getattr(last_msg, 'content', '')))}"
                    )

            # Inject stored thought_signatures for clients that don't preserve extra_content
            session_id = getattr(request_data, "session_id", None) or ""
            self._inject_thought_signatures(canonical_request, session_id)

            # Convert from canonical/domain format to Gemini API format
            gemini_request = self.translation_service.from_domain_to_gemini_request(
                canonical_request
            )

            # Use mixin method to convert system messages (KiloCode's approach)
            # This avoids the 64K token limit on the separate systemInstruction field
            final_contents = self._convert_system_messages_for_code_assist(
                gemini_request
            )

            # Use mixin method to build Code Assist API request
            code_assist_request = self._build_code_assist_request(
                gemini_request, final_contents
            )

            # Strip/repair unsupported tool definitions (e.g., custom tools from clients)
            # This is critical for Droid/Factory CLI compatibility which sends tools
            # with type: "custom" and input_schema instead of function parameters
            self._sanitize_code_assist_tools(canonical_request, code_assist_request)

            prompt_tokens_estimate = self._estimate_prompt_tokens(code_assist_request)
            self._enforce_prompt_limit(
                prompt_tokens_estimate,
                effective_model,
                request_id=getattr(request_data, "id", None),
            )

            # Define request body builder as closure for use in stream_generator
            # This allows retry logic to rebuild request body with modified tools
            def _build_request_body() -> dict[str, Any]:
                return self._build_code_assist_request_body(
                    effective_model=effective_model,
                    project_id=project_id,
                    request_data=request_data,
                    code_assist_request=code_assist_request,
                )

            # Log request details for debugging token issues
            if logger.isEnabledFor(logging.DEBUG):
                first_msg_size = 0
                contents_list = code_assist_request.get("contents", [])
                if contents_list and len(contents_list) > 0:
                    first_msg_parts = contents_list[0].get("parts", [])
                    for part in first_msg_parts:
                        if "text" in part:
                            first_msg_size += len(part["text"])
                logger.debug(
                    f"Code Assist request: first message size={first_msg_size} chars, "
                    f"contents count={len(contents_list)}, "
                    f"estimated tokens={prompt_tokens_estimate}"
                )

            prompt_tokens = prompt_tokens_estimate

            # Use the Code Assist API with streaming endpoint
            url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
            logger.info(f"Making streaming Code Assist API call to: {url}")

            # For token calculation
            encoding = _get_tiktoken_encoding()
            if prompt_tokens is None:
                try:
                    prompt_text_parts = []
                    if code_assist_request.get("systemInstruction"):
                        for part in code_assist_request["systemInstruction"].get(
                            "parts", []
                        ):
                            if "text" in part:
                                prompt_text_parts.append(part["text"])
                    for content in code_assist_request.get("contents", []):
                        for part in content.get("parts", []):
                            if "text" in part:
                                prompt_text_parts.append(part["text"])
                    full_prompt = "\n".join(prompt_text_parts)
                    prompt_tokens = len(encoding.encode(full_prompt))
                except Exception as e:
                    logger.warning(
                        f"Could not calculate prompt tokens with tiktoken: {e}"
                    )
                    prompt_tokens = 0

            async def stream_generator(
                *,
                allow_tool_retry: bool = True,
                without_tools: bool = False,
            ) -> AsyncGenerator[ProcessedResponse, None]:
                import json

                response = None
                generated_text = ""
                error_json_buffer: str | None = None
                google_auth_exceptions = _get_google_auth_exceptions()

                def _should_skip_chunk(chunk: dict[str, Any]) -> bool:
                    """Filter out empty deltas so clients don't receive blank messages.

                    NOTE: Usage-only chunks (with empty choices but usage data) should
                    NOT be skipped - they contain important token count information.
                    NOTE: Stop chunks (finish_reason=stop) should NOT be skipped -
                    they are needed to merge usage data per OpenRouter API spec.
                    """
                    if not chunk:
                        return True
                    choices = chunk.get("choices") or []

                    # Preserve usage-only chunks even if choices is empty
                    if not choices:
                        # Don't skip if chunk has usage data; skip otherwise
                        return not chunk.get("usage")

                    choice = choices[0] or {}
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason")

                    # Normalize finish_reason to lowercase for consistency
                    if isinstance(finish_reason, str):
                        finish_reason = finish_reason.lower()
                        choice["finish_reason"] = finish_reason

                    has_content = bool(delta.get("content"))
                    has_tools = bool(delta.get("tool_calls"))
                    has_reasoning = bool(
                        delta.get("reasoning_content") or delta.get("reasoning")
                    )

                    if has_tools and not finish_reason:
                        choice["finish_reason"] = "tool_calls"
                        return False

                    if has_content or has_tools or has_reasoning:
                        return False

                    # Preserve explicit terminal states even without content
                    # Stop chunks are needed for usage data merging
                    if finish_reason in {
                        "error",
                        "tool_calls",
                        "stop",
                        "stop_sequence",
                    }:
                        return False
                    # Skip length/cancelled without content
                    if finish_reason in {"length", "cancelled"}:
                        return True
                    return True

                def _build_error_chunk(
                    message: str, *, code: int = 500, error_type: str = "api_error"
                ) -> dict[str, Any]:
                    now = int(time.time())
                    return {
                        "id": f"chatcmpl-error-{now}",
                        "object": "chat.completion.chunk",
                        "created": now,
                        "model": effective_model,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "error"}
                        ],
                        "error": {"message": message, "type": error_type, "code": code},
                    }

                try:
                    try:
                        if without_tools:
                            code_assist_request.pop("tools", None)
                            code_assist_request.pop("toolConfig", None)
                        request_body = _build_request_body()
                        if logger.isEnabledFor(logging.DEBUG):
                            tools_snapshot = request_body.get("request", {}).get(
                                "tools"
                            )
                            if tools_snapshot:
                                try:
                                    logger.debug(
                                        "Code Assist sanitized tools payload: %s",
                                        json.dumps(tools_snapshot)[:1000],
                                    )
                                except Exception:
                                    logger.debug(
                                        "Code Assist sanitized tools payload present (non-serializable)"
                                    )
                        response = await asyncio.to_thread(
                            auth_session.request,
                            method="POST",
                            url=url,
                            params={"alt": "sse"},
                            json=request_body,
                            headers={"Content-Type": "application/json"},
                            timeout=int(DEFAULT_READ_TIMEOUT),
                            stream=True,
                        )
                    except requests.exceptions.Timeout as te:
                        logger.error(
                            f"Streaming timeout calling {url}: {te}", exc_info=True
                        )
                        error_chunk = _build_error_chunk(
                            "Gateway timeout reaching Code Assist streaming endpoint.",
                            code=504,
                        )
                        yield ProcessedResponse(
                            content=error_chunk,
                            metadata={
                                "finish_reason": "error",
                                "error": error_chunk["error"],
                                "id": error_chunk["id"],
                                "model": error_chunk["model"],
                                "created": error_chunk["created"],
                            },
                        )
                        return
                    except requests.exceptions.RequestException as rexc:
                        logger.error(
                            f"Streaming connection error calling {url}: {rexc}",
                            exc_info=True,
                        )
                        error_chunk = _build_error_chunk(
                            "Connection error reaching Code Assist streaming endpoint.",
                            code=503,
                        )
                        yield ProcessedResponse(
                            content=error_chunk,
                            metadata={
                                "finish_reason": "error",
                                "error": error_chunk["error"],
                                "id": error_chunk["id"],
                                "model": error_chunk["model"],
                                "created": error_chunk["created"],
                            },
                        )
                        return
                    except google_auth_exceptions.GoogleAuthError as gae:
                        logger.error(
                            f"Streaming auth error calling {url}: {gae}",
                            exc_info=True,
                        )
                        error_chunk = {
                            "id": f"chatcmpl-error-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": effective_model,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": "error"}
                            ],
                            "error": {
                                "message": "Authentication failed. Please check your credentials.",
                                "type": "auth_error",
                                "code": 401,
                            },
                        }
                        yield ProcessedResponse(
                            content=error_chunk,
                            metadata={
                                "finish_reason": "error",
                                "error": error_chunk["error"],
                                "id": error_chunk["id"],
                                "model": error_chunk["model"],
                                "created": error_chunk["created"],
                            },
                        )
                        return

                    if response.status_code != 200:
                        # Capture and log error response body for debugging
                        try:
                            error_body = response.json()
                            logger.warning(
                                f"Gemini streaming error response: {response.status_code}, "
                                f"error: {error_body}"
                            )
                        except Exception:
                            error_body_text = response.text
                            logger.warning(
                                f"Gemini streaming error response: {response.status_code}, "
                                f"body: {error_body_text[:500]}"
                            )
                        # Handle 429 with graceful degradation
                        if response.status_code == 429:
                            if self._degradation_config.enabled:
                                try:
                                    # Parse error details for retry delay extraction
                                    try:
                                        error_detail = response.json()
                                    except Exception:
                                        error_detail = response.text
                                        
                                    # Create a temporary error object to pass details
                                    quota_error = BackendError(
                                        message="Rate limit exceeded",
                                        code="rate_limit_exceeded",
                                        status_code=429,
                                        details=error_detail if isinstance(error_detail, dict) else {"raw": error_detail}
                                    )
                                    
                                    fallback_response = await self._handle_429_with_graceful_degradation(
                                        original_model=effective_model,
                                        request_data=request_data,
                                        processed_messages=processed_messages,
                                        error=quota_error,
                                        **kwargs,
                                    )
                                except BackendError:
                                    fallback_response = None
                                else:
                                    if isinstance(
                                        fallback_response, StreamingResponseEnvelope
                                    ):
                                        if fallback_response.content is not None:
                                            async for (
                                                fallback_chunk
                                            ) in fallback_response.content:
                                                yield fallback_chunk
                                    elif isinstance(
                                        fallback_response, ResponseEnvelope
                                    ):
                                        yield self._response_envelope_to_stream_chunk(
                                            fallback_response, effective_model
                                        )
                                    return

                            error_detail: Any
                            try:
                                error_detail = response.json()
                            except Exception:
                                error_detail = response.text

                            error_message = (
                                "Service temporarily unavailable due to rate limiting."
                            )
                            error_code: int | None = 429
                            error_type = "rate_limit_exceeded"

                            if isinstance(error_detail, dict):
                                detail_error = error_detail.get("error") or {}
                                status_val = str(detail_error.get("status", "")).upper()
                                if status_val == "RESOURCE_EXHAUSTED":
                                    error_type = "quota_exceeded"

                                message_val = detail_error.get("message")
                                if isinstance(message_val, str) and message_val.strip():
                                    if error_type == "quota_exceeded":
                                        error_message = (
                                            "Service temporarily unavailable due to rate limiting. "
                                            f"Details: {message_val}"
                                        )
                                    else:
                                        error_message = message_val

                                error_code = cast(
                                    int | None, detail_error.get("code", error_code)
                                )

                            if error_type == "quota_exceeded":
                                error_code = 503

                            error_chunk = {
                                "id": f"chatcmpl-error-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": effective_model,
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": "error"}
                                ],
                                "error": {
                                    "message": error_message,
                                    "type": error_type,
                                    "code": error_code,
                                },
                            }
                            # Surface the 429 immediately instead of blocking on retries
                            yield ProcessedResponse(
                                content=error_chunk,
                                metadata={
                                    "finish_reason": "error",
                                    "error": error_chunk["error"],
                                    "id": error_chunk["id"],
                                    "model": error_chunk["model"],
                                    "created": error_chunk["created"],
                                },
                            )
                            # Put specific model in cooldown for quota errors
                            # but keep backend functional for other models
                            if error_type == "quota_exceeded":
                                self._set_cooldown(effective_model)
                            return

                        # For non-429 errors, yield error chunk (with optional retry sans tools)
                        # Graceful error handling - yield error chunk instead of raising exception
                        try:
                            error_detail = response.json()
                        except Exception:
                            error_detail = response.text

                        error_message = ""
                        raw_message = ""
                        if isinstance(error_detail, dict):
                            error_message = error_detail.get("error", {}).get(
                                "message", ""
                            )
                            raw_message = error_detail.get("error", {}).get(
                                "message", ""
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
                            # Put specific model in cooldown, keep backend functional
                            self._set_cooldown(effective_model)
                            # Extract user-friendly error message
                            user_message = (
                                "Service temporarily unavailable due to rate limiting."
                            )
                            if isinstance(error_detail, dict):
                                detail_msg = error_detail.get("error", {}).get(
                                    "message"
                                )
                                if isinstance(detail_msg, str) and detail_msg.strip():
                                    if is_quota_error:
                                        user_message = (
                                            "Service temporarily unavailable due to rate limiting. "
                                            f"Details: {detail_msg}"
                                        )
                                    else:
                                        user_message = detail_msg
                            # Yield quota error chunk instead of raising exception
                            quota_code = 503
                            error_chunk = {
                                "id": f"chatcmpl-error-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": effective_model,
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": "error"}
                                ],
                                "error": {
                                    "message": user_message,
                                    "type": "quota_exceeded",
                                    "code": quota_code,
                                },
                            }
                            yield ProcessedResponse(
                                content=error_chunk,
                                metadata={
                                    "finish_reason": "error",
                                    "error": error_chunk["error"],
                                    "id": error_chunk["id"],
                                    "model": error_chunk["model"],
                                    "created": error_chunk["created"],
                                },
                            )
                            return
                        else:
                            # Detect schema/tool validation errors and retry once without tools/toolConfig
                            schema_error = False
                            if response.status_code == 400 and isinstance(
                                error_detail, dict
                            ):
                                lower_msg = (raw_message or error_message or "").lower()
                                schema_error = (
                                    "input_schema" in lower_msg or "custom" in lower_msg
                                )

                            if schema_error:
                                logger.info(
                                    "Retrying Code Assist request without tools due to schema error: %s",
                                    raw_message or error_message,
                                )
                                response.close()
                                # Retry once without tools/toolConfig
                                async for retry_chunk in stream_generator(
                                    allow_tool_retry=False, without_tools=True
                                ):
                                    yield retry_chunk
                                return

                            # Extract user-friendly error message
                            user_message = "An API error occurred. Please try again."
                            if isinstance(error_detail, dict):
                                user_message = error_detail.get("error", {}).get(
                                    "message", user_message
                                )
                            # Yield general error chunk instead of raising exception
                            error_chunk = {
                                "id": f"chatcmpl-error-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": effective_model,
                                "choices": [
                                    {"index": 0, "delta": {}, "finish_reason": "error"}
                                ],
                                "error": {
                                    "message": user_message,
                                    "type": "api_error",
                                    "code": response.status_code,
                                },
                            }
                            yield ProcessedResponse(
                                content=error_chunk,
                                metadata={
                                    "finish_reason": "error",
                                    "error": error_chunk["error"],
                                    "id": error_chunk["id"],
                                    "model": error_chunk["model"],
                                    "created": error_chunk["created"],
                                },
                            )
                            return

                    line_buffer = ""
                    done = False

                    def _process_decoded_line(
                        decoded_line: str,
                    ) -> Iterable[ProcessedResponse]:
                        nonlocal done, generated_text, error_json_buffer

                        if not decoded_line:
                            return

                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[6:].strip()
                            if data_str == "[DONE]":
                                done = True
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    "Received malformed JSON chunk in streaming response: %s (error: %s)",
                                    (
                                        data_str[:100] + "..."
                                        if len(data_str) > 100
                                        else data_str
                                    ),
                                    str(e),
                                )
                                if data_str and not data_str.strip().endswith("}"):
                                    logger.error(
                                        "Detected incomplete JSON chunk, yielding error response"
                                    )
                                    error_chunk = _build_error_chunk(
                                        "Malformed streaming chunk from Code Assist.",
                                        code=502,
                                    )
                                    yield ProcessedResponse(
                                        content=error_chunk,
                                        metadata={
                                            "finish_reason": "error",
                                            "error": error_chunk["error"],
                                            "id": error_chunk["id"],
                                            "model": error_chunk["model"],
                                            "created": error_chunk["created"],
                                        },
                                    )
                                    done = True
                                return

                            try:
                                if logger.isEnabledFor(TRACE_LEVEL):
                                    logger.log(
                                        TRACE_LEVEL,
                                        "[STREAMING] Received chunk from backend: choices_count=%s, has_usage=%s, has_id=%s",
                                        len(data.get("choices", [])),
                                        "usage" in data,
                                        "id" in data,
                                    )
                                domain_chunk = (
                                    self.translation_service.to_domain_stream_chunk(
                                        chunk=data, source_format="code_assist"
                                    )
                                )
                                if domain_chunk is not None:
                                    # Ensure we use the effective model name, not what the backend returns
                                    # This prevents leaking internal model names like 'code-assist-model'
                                    domain_chunk["model"] = effective_model
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
                            except Exception as e:
                                logger.error(
                                    "Failed to process streaming chunk: %s", str(e)
                                )
                                error_chunk = _build_error_chunk(
                                    "Failed to parse streaming chunk from Code Assist.",
                                    code=500,
                                )
                                yield ProcessedResponse(
                                    content=error_chunk,
                                    metadata={
                                        "finish_reason": "error",
                                        "error": error_chunk["error"],
                                        "id": error_chunk["id"],
                                        "model": error_chunk["model"],
                                        "created": error_chunk["created"],
                                    },
                                )
                                done = True
                                return

                            if domain_chunk and domain_chunk.get("choices"):
                                if _should_skip_chunk(domain_chunk):
                                    return
                                choice = domain_chunk["choices"][0]
                                delta = choice.get("delta", {}) or {}
                                text_piece = delta.get("content")
                                if text_piece:
                                    generated_text += text_piece
                                    if error_json_buffer is None:
                                        stripped_piece = text_piece.lstrip()
                                        if stripped_piece.startswith("{"):
                                            error_json_buffer = stripped_piece
                                    else:
                                        error_json_buffer += text_piece

                                    if error_json_buffer:
                                        candidate_json = error_json_buffer.strip()
                                        try:
                                            parsed_error = json.loads(candidate_json)
                                        except json.JSONDecodeError:
                                            pass
                                        else:
                                            error_json_buffer = None
                                            if isinstance(parsed_error, dict) and (
                                                "error" in parsed_error
                                            ):
                                                error_info = (
                                                    parsed_error.get("error") or {}
                                                )
                                                error_code = cast(
                                                    int | None, error_info.get("code")
                                                )
                                                error_status = str(
                                                    error_info.get("status", "")
                                                ).upper()
                                                error_message = error_info.get(
                                                    "message", ""
                                                )

                                                if error_code == 429 or (
                                                    error_status == "RESOURCE_EXHAUSTED"
                                                ):
                                                    error_chunk = _build_error_chunk(
                                                        error_message
                                                        or "Service temporarily unavailable due to rate limiting. Please try again in a few minutes.",
                                                        code=int(error_code or 429),
                                                        error_type=(
                                                            "quota_exceeded"
                                                            if error_status
                                                            == "RESOURCE_EXHAUSTED"
                                                            else "rate_limit_exceeded"
                                                        ),
                                                    )
                                                    with contextlib.suppress(Exception):
                                                        response.close()
                                                    yield ProcessedResponse(
                                                        content=error_chunk,
                                                        metadata={
                                                            "finish_reason": "error",
                                                            "error": error_chunk[
                                                                "error"
                                                            ],
                                                            "id": error_chunk["id"],
                                                            "model": error_chunk[
                                                                "model"
                                                            ],
                                                            "created": error_chunk[
                                                                "created"
                                                            ],
                                                        },
                                                    )
                                                    done = True
                                                    return

                                                error_message = (
                                                    error_message
                                                    or "API error received from Gemini Code Assist"
                                                )
                                                error_code_value = (
                                                    error_code
                                                    if isinstance(error_code, int)
                                                    else 500
                                                )
                                                error_chunk = {
                                                    "id": f"chatcmpl-error-{int(time.time())}",
                                                    "object": "chat.completion.chunk",
                                                    "created": int(time.time()),
                                                    "model": effective_model,
                                                    "choices": [
                                                        {
                                                            "index": 0,
                                                            "delta": {},
                                                            "finish_reason": "error",
                                                        }
                                                    ],
                                                    "error": {
                                                        "message": error_message,
                                                        "type": "api_error",
                                                        "code": error_code_value,
                                                        "status": error_status or None,
                                                    },
                                                }
                                                with contextlib.suppress(Exception):
                                                    response.close()
                                                yield ProcessedResponse(
                                                    content=error_chunk,
                                                    metadata={
                                                        "finish_reason": "error",
                                                        "error": error_chunk["error"],
                                                        "id": error_chunk["id"],
                                                        "model": error_chunk["model"],
                                                        "created": error_chunk[
                                                            "created"
                                                        ],
                                                    },
                                                )
                                                done = True
                                                return
                                            else:
                                                error_json_buffer = None

                            metadata = create_gemini_response_metadata(
                                model=effective_model,
                                usage=None,
                                key_name=getattr(self, "_key_name", None),
                            ).model_dump()

                            raw_tool_calls = (
                                domain_chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("tool_calls")
                            )
                            metadata.update(
                                {
                                    "raw_tool_calls": raw_tool_calls,
                                    "raw_finish_reason": domain_chunk.get(
                                        "choices", [{}]
                                    )[0].get("finish_reason"),
                                    "model": effective_model,
                                }
                            )

                            # Store thought_signatures server-side for clients that don't preserve extra_content
                            # (e.g., Droid). This allows us to inject signatures in subsequent requests.
                            if raw_tool_calls and isinstance(raw_tool_calls, list):
                                session_id = (
                                    getattr(request_data, "session_id", None) or ""
                                )
                                for tc in raw_tool_calls:
                                    if not isinstance(tc, dict):
                                        continue
                                    tc_id = tc.get("id", "")
                                    extra = tc.get("extra_content")
                                    if isinstance(extra, dict):
                                        google_extra = extra.get("google", {})
                                        sig = google_extra.get("thought_signature")
                                        if sig and tc_id:
                                            cache_key = f"{session_id}:{tc_id}"
                                            GeminiOAuthBaseConnector._thought_signature_cache[
                                                cache_key
                                            ] = sig
                                            logger.debug(
                                                "Stored thought_signature for tool_call_id=%s (session=%s)",
                                                tc_id,
                                                (
                                                    session_id[:8]
                                                    if session_id
                                                    else "none"
                                                ),
                                            )

                            yield ProcessedResponse(
                                content=domain_chunk,
                                metadata=metadata,
                            )
                            return

                        if decoded_line.strip():
                            passthrough_chunk = (
                                self.translation_service.to_domain_stream_chunk(
                                    chunk={"text": decoded_line},
                                    source_format="raw_text",
                                )
                            )
                            if passthrough_chunk and not _should_skip_chunk(
                                passthrough_chunk
                            ):
                                yield ProcessedResponse(content=passthrough_chunk)

                        return

                    # Buffer for the final chunk that contains the stop reason
                    final_stop_chunk = None

                    try:
                        for chunk in response.iter_content(
                            chunk_size=4096, decode_unicode=False
                        ):
                            if done:
                                break

                            try:
                                chunk_str = (
                                    chunk
                                    if isinstance(chunk, bytes)
                                    else str(chunk).encode()
                                ).decode(
                                    "utf-8"
                                )  # type: ignore[union-attr]
                            except (UnicodeDecodeError, AttributeError):
                                continue

                            line_buffer += chunk_str
                            lines = line_buffer.splitlines(keepends=True)

                            # If the last line is incomplete (no newline), keep it buffered
                            if lines and not lines[-1].endswith(("\n", "\r")):
                                line_buffer = lines.pop()  # keep partial
                            else:
                                line_buffer = ""

                            for line in lines:
                                decoded_line = line.rstrip("\r\n")

                                for processed_chunk in _process_decoded_line(
                                    decoded_line
                                ):
                                    # Check if this chunk signals the end of the stream
                                    # If so, buffer it and yield it AFTER usage
                                    content = processed_chunk.content
                                    is_stop_chunk = False

                                    if isinstance(content, dict):
                                        choices = content.get("choices", [])
                                        if choices and isinstance(choices[0], dict):
                                            finish_reason = choices[0].get(
                                                "finish_reason"
                                            )
                                            if finish_reason:
                                                logger.debug(
                                                    f"[STREAMING] Found chunk with finish_reason: {finish_reason}"
                                                )

                                            if finish_reason in (
                                                "stop",
                                                "stop_sequence",
                                            ):
                                                is_stop_chunk = True

                                    if is_stop_chunk:
                                        if logger.isEnabledFor(TRACE_LEVEL):
                                            logger.log(
                                                TRACE_LEVEL,
                                                "[STREAMING] Buffering stop chunk",
                                            )
                                        final_stop_chunk = processed_chunk
                                        # Do not yield yet - wait for usage
                                        continue

                                    yield processed_chunk
                                    # Yield control to the event loop to allow sending
                                    # chunks to the client immediately
                                    await asyncio.sleep(0)
                                if done:
                                    break

                        if not done and line_buffer:
                            for processed_chunk in _process_decoded_line(
                                line_buffer.rstrip("\r\n")
                            ):
                                # Same check for buffered lines
                                content = processed_chunk.content
                                is_stop_chunk = False
                                if isinstance(content, dict):
                                    choices = content.get("choices", [])
                                    if choices and isinstance(choices[0], dict):
                                        finish_reason = choices[0].get("finish_reason")
                                        if finish_reason in ("stop", "stop_sequence"):
                                            is_stop_chunk = True

                                if is_stop_chunk:
                                    if logger.isEnabledFor(TRACE_LEVEL):
                                        logger.log(
                                            TRACE_LEVEL,
                                            "[STREAMING] Buffering stop chunk (from buffer)",
                                        )
                                    final_stop_chunk = processed_chunk
                                    continue

                                yield processed_chunk
                                # Yield control to the event loop
                                await asyncio.sleep(0)
                            line_buffer = ""

                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                f"[STREAMING] Completed chunk loop. final_stop_chunk captured: {final_stop_chunk is not None}",
                            )

                    except GeneratorExit:
                        logger.debug("Stream closed by consumer before completion")
                        raise
                    except Exception as e:
                        logger.error(
                            f"Error in streaming generator: {e}", exc_info=True
                        )
                        raise

                    # Calculate usage and merge into final stop chunk
                    # Per OpenRouter API spec, usage should be in the final chunk
                    # with finish_reason="stop", NOT as a separate usage-only chunk
                    usage: dict[str, Any] | None = None
                    try:
                        completion_tokens = len(encoding.encode(generated_text))
                        usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": (prompt_tokens or 0) + completion_tokens,
                        }
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL, f"[STREAMING] Calculated usage: {usage}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Could not calculate completion tokens for streaming: {e}"
                        )

                    # Yield the final stop chunk with usage merged in
                    # Import the protective wrapper to detect accidental stringification
                    from src.core.ports.streaming_contracts import StopChunkWithUsage

                    if final_stop_chunk:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "[STREAMING] Yielding final stop chunk with usage",
                            )
                        # Merge usage into the final stop chunk content
                        final_content = final_stop_chunk.content
                        if isinstance(final_content, dict) and usage:
                            final_content = dict(
                                final_content
                            )  # Copy to avoid mutation
                            final_content["usage"] = usage
                            # Wrap with StopChunkWithUsage to detect accidental
                            # stringification. If any code tries to str() this dict,
                            # it will raise UsageChunkLeakError with a stack trace.
                            final_content = StopChunkWithUsage(final_content)
                        yield ProcessedResponse(
                            content=final_content,
                            metadata=final_stop_chunk.metadata,
                            usage=usage,
                        )
                    else:
                        logger.debug(
                            "[STREAMING] No stop chunk buffered, yielding generic stop with usage"
                        )
                        # Fallback: create a generic stop chunk if none was captured
                        # (e.g. if stream ended without explicit stop reason)
                        final_chunk = self.translation_service.to_domain_stream_chunk(
                            chunk=None, source_format="code_assist"
                        )
                        # Merge usage and correct model into the generic stop chunk
                        if isinstance(final_chunk, dict):
                            # Override the default model name with the actual effective model
                            final_chunk["model"] = effective_model
                            if usage:
                                final_chunk["usage"] = usage
                            # Wrap with protective class
                            final_chunk = StopChunkWithUsage(final_chunk)
                        yield ProcessedResponse(
                            content=final_chunk,
                            usage=usage,
                            metadata={"model": effective_model},
                        )

                except BackendError as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    raise
                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    # Build proper error chunk with full error details
                    now = int(time.time())
                    error_message = str(e) if str(e) else "An unexpected error occurred"
                    error_chunk = {
                        "id": f"chatcmpl-error-{now}",
                        "object": "chat.completion.chunk",
                        "created": now,
                        "model": effective_model,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "error"}
                        ],
                        "error": {
                            "message": error_message,
                            "type": "internal_error",
                            "code": 500,
                        },
                    }
                    yield ProcessedResponse(
                        content=error_chunk,
                        metadata={
                            "finish_reason": "error",
                            "error": error_chunk["error"],
                            "id": error_chunk["id"],
                            "model": error_chunk["model"],
                            "created": error_chunk["created"],
                        },
                    )
                finally:
                    if response is not None:
                        with contextlib.suppress(Exception):
                            response.close()

            return StreamingResponseEnvelope(
                content=stream_generator(),
                media_type="text/event-stream",
                headers={},
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
                logger.info("Backend rate limited during streaming API call: %s", e)
            else:
                logger.error(
                    f"Backend error during streaming API call: {e}", exc_info=True
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

    def _response_envelope_to_stream_chunk(
        self, response: ResponseEnvelope, model: str
    ) -> ProcessedResponse:
        """Convert a non-streaming response into a single streaming chunk."""
        created_ts = int(time.time())
        chunk_id = f"chatcmpl-fallback-{created_ts}"

        text_content: str
        if isinstance(response.content, str):
            text_content = response.content
        elif isinstance(response.content, dict):
            text_content = (
                response.content.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            if not text_content:
                text_content = json.dumps(response.content)
        else:
            text_content = str(response.content or "")

        payload = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": text_content},
                    "finish_reason": "stop",
                }
            ],
        }

        metadata: dict[str, Any] = {
            "finish_reason": "stop",
            "id": chunk_id,
            "model": model,
            "created": created_ts,
            "graceful_degradation": True,
        }
        if response.usage:
            metadata["usage"] = response.usage

        return ProcessedResponse(
            content=payload, metadata=metadata, usage=response.usage
        )

    def _generate_user_prompt_id(self, request_data: Any) -> str:
        """Generate a unique user_prompt_id for Code Assist requests."""
        session_hint: str | None = None
        extra_body = getattr(request_data, "extra_body", None)
        if isinstance(extra_body, dict):
            raw_session = extra_body.get("session_id") or extra_body.get(
                "user_prompt_id"
            )
            if raw_session is not None:
                session_hint = str(raw_session)

        base = "proxy"
        if session_hint:
            safe_session = "".join(
                c if c.isalnum() or c in "-._" else "-" for c in session_hint
            ).strip("-")
            if safe_session:
                base = f"{base}-{safe_session}"

        return f"{base}-{uuid.uuid4().hex}"

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
            elif role == "user":
                conversation_context.append(f"User: {content}")
            elif role == "assistant":
                conversation_context.append(f"Assistant: {content}")

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

        This method builds the generationConfig including thinkingConfig for models
        that support thinking/reasoning (like gemini-2.5-pro, gemini-3-pro).
        """
        # Extract parameters with defaults
        temperature = float(getattr(request_data, "temperature", 0.7))
        max_tokens = int(getattr(request_data, "max_tokens", 1024))
        top_p = float(getattr(request_data, "top_p", 0.95))
        top_k = getattr(request_data, "top_k", None)

        # Create generation config using Pydantic model
        config = create_gemini_generation_config(
            temperature=temperature,
            top_p=top_p,
            max_output_tokens=max_tokens,
            top_k=int(top_k) if top_k is not None else None,
        )

        # Convert to Gemini API format
        cfg = config.model_dump()

        # Convert field names to Code Assist API format
        if "max_output_tokens" in cfg:
            cfg["maxOutputTokens"] = cfg.pop("max_output_tokens")
        if "top_p" in cfg:
            cfg["topP"] = cfg.pop("top_p")
        if "top_k" in cfg:
            cfg["topK"] = cfg.pop("top_k")

        # Add thinkingConfig for thinking/reasoning support
        # This enables the model to include reasoning content in responses
        thinking_budget = getattr(request_data, "thinking_budget", None)
        reasoning_effort = getattr(request_data, "reasoning_effort", None)

        # Map reasoning_effort to thinking_budget if thinking_budget not explicit
        if thinking_budget is None and reasoning_effort is not None:
            effort_to_budget: dict[str, int] = {
                "low": 512,
                "medium": 2048,
                "high": -1,  # -1 means unlimited
            }
            thinking_budget = effort_to_budget.get(
                reasoning_effort.lower() if isinstance(reasoning_effort, str) else "",
                None,
            )

        # Default to medium thinking budget if not specified to enable reasoning
        # This ensures Code Assist models produce reasoning content by default
        if thinking_budget is None:
            thinking_budget = 2048  # Default medium thinking budget

        cfg["thinkingConfig"] = {
            "thinkingBudget": thinking_budget,
            "includeThoughts": True,
        }

        return cfg

    def _convert_from_code_assist_format(
        self, code_assist_response: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert Code Assist API response to OpenAI-compatible format."""
        # Extract the generated text from Code Assist response
        # Code Assist API wraps the response in a "response" object
        response_wrapper = code_assist_response.get("response", {})
        candidates = response_wrapper.get("candidates", [])
        generated_text = ""

        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            if parts and len(parts) > 0:
                generated_text = parts[0].get("text", "")

        # Create OpenAI-compatible response
        openai_response = {
            "id": f"code-assist-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": generated_text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # Code Assist API doesn't provide token counts
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

        return openai_response

    def _get_fallback_model(self, original_model: str) -> str | list[str] | None:
        """Get the fallback model for a given model."""
        return get_fallback_model(original_model)

    def _is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown."""
        return is_model_in_cooldown(model, self._model_retry_states)

    def _extract_retry_delay(self, error: BackendError) -> float | None:
        """Extract retry delay from error details.

        Handles both 'retryDelay' (Google RPC RetryInfo) and 'quotaResetDelay'
        (Google RPC ErrorInfo metadata).
        """
        if not error.details:
            return None

        # Get the inner error object if present (from _extract_generated_text_from_response)
        error_data = error.details.get("error", error.details)

        # Check details list
        details_list = error_data.get("details")
        if not isinstance(details_list, list):
            return None

        for detail in details_list:
            if not isinstance(detail, dict):
                continue

            type_url = detail.get("@type", "")

            # Case 1: RetryInfo with retryDelay
            if "RetryInfo" in type_url:
                delay_str = detail.get("retryDelay")
                if isinstance(delay_str, str):
                    return self._parse_duration_string(delay_str)

            # Case 2: ErrorInfo with quotaResetDelay in metadata
            if "ErrorInfo" in type_url:
                metadata = detail.get("metadata")
                if isinstance(metadata, dict):
                    reset_delay = metadata.get("quotaResetDelay")
                    if isinstance(reset_delay, str):
                        return self._parse_duration_string(reset_delay)

        return None

    @staticmethod
    def _parse_duration_string(duration: str) -> float | None:
        """Parse duration string like '10s' or '4h51m33.9s'."""
        try:
            # Simple seconds format (e.g. "17493.989s")
            if duration.endswith("s") and "m" not in duration and "h" not in duration:
                return float(duration[:-1])

            # Complex format (e.g. "4h51m33.989s")
            total_seconds = 0.0
            current_val = ""

            for char in duration:
                if char.isdigit() or char == ".":
                    current_val += char
                elif char == "h":
                    total_seconds += float(current_val) * 3600
                    current_val = ""
                elif char == "m":
                    total_seconds += float(current_val) * 60
                    current_val = ""
                elif char == "s":
                    total_seconds += float(current_val)
                    current_val = ""

            return total_seconds if total_seconds > 0 else None
        except Exception:
            return None

    def _set_cooldown(self, model: str, duration: float | None = None) -> None:
        """Put a model into cooldown state.

        Args:
            model: The model to put in cooldown
            duration: Optional custom duration in seconds. If None, uses default config.
        """
        cooldown = (
            duration
            if duration is not None
            else self._degradation_config.cooldown_duration
        )
        set_model_cooldown(model, self._model_retry_states, cooldown)

    @staticmethod
    def _is_rate_limit_like_error(error: BackendError) -> bool:
        """Determine whether an error should trigger graceful degradation retries."""
        return is_rate_limit_like_error(error)

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
        if not self._degradation_config.enable_recovery_probing:
            return False

        state = self._model_retry_states.get(model)
        if not state or not self._is_in_cooldown(model):
            return True

        # Check if enough time has passed since last probe
        now = time.time()
        if (
            not bypass_interval_check
            and now - state.last_probe_attempt
            < self._degradation_config.recovery_probe_interval
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
            asyncio.create_task(self._handle_credentials_file_change())
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
        """Handle 429 errors with graceful degradation.

        This method implements the expected behavior:
        1. For gemini-2.5-pro: retry with delays, then fallback to gemini-2.5-flash
        2. For gemini-2.5-flash: retry with delays, then mark backend as unusable
        """
        # Prevent recursive graceful degradation calls
        if _in_graceful_degradation:
            raise BackendError(
                message="Recursive graceful degradation detected",
                code="recursive_graceful_degradation",
                status_code=429,
            )

        # Track attempts per request (not globally) to prevent premature exhaustion
        request_attempts = 0

        if not self._degradation_config.enabled:
            # If graceful degradation is disabled, use original behavior
            # Mark backend as completely unusable (not just quota exceeded)
            self._quota_exceeded = True
            self.is_functional = False
            logger.error(
                "Backend %s marked as unusable due to rate limit and graceful degradation disabled. "
                "Manual intervention may be required to restore functionality.",
                self.name,
            )
            raise BackendError(
                message="Rate limit exceeded and graceful degradation is disabled",
                code="rate_limit_exceeded",
                status_code=429,
            )

        models_to_try = [original_model]
        disable_fallback = False
        try:
            disable_fallback = bool(self.config.backends.disable_gemini_oauth_fallback)
        except AttributeError:  # pragma: no cover - defensive for legacy configs
            disable_fallback = False

        fallback_model = (
            None if disable_fallback else self._get_fallback_model(original_model)
        )
        if fallback_model:
            if isinstance(fallback_model, list):
                models_to_try.extend(fallback_model)
            else:
                models_to_try.append(fallback_model)

        start_time = time.time()
        self._graceful_metrics.total_invocations += 1

        for _, model in enumerate(models_to_try):
            # Reset attempts for this model if needed
            if model not in self._model_retry_states:
                self._model_retry_states[model] = ModelRetryState()

            state = self._model_retry_states[model]
            
            # Check if the initial error dictates a long cooldown for the original model
            # This prevents "spamming" the API when it has already told us to wait
            if model == original_model and error and self._is_rate_limit_like_error(error):
                retry_delay = self._extract_retry_delay(error)
                # If delay is significant (e.g. > 10s), respect it immediately
                # For short delays (e.g. 1s), we might still attempt retries with backoff
                if retry_delay and retry_delay > 10.0:
                    self._set_cooldown(model, duration=retry_delay)
                    logger.warning(
                        "Model %s returned 429 with long retry delay (%.1fs); skipping retries and setting cooldown.",
                        model,
                        retry_delay,
                    )
                    # Skip retries for this model, proceed to fallback
                    continue

            # If model is in cooldown, try to recover it first
            if self._is_in_cooldown(model):
                # For inline recovery, we need to fully recover the model (2 successful probes)
                # Keep trying until either recovery succeeds or we give up
                recovered = False
                max_inline_probes = 4  # Prevent infinite loops
                for _ in range(max_inline_probes):
                    # Store probe success count before the call to detect partial progress
                    current_state: ModelRetryState | None = (
                        self._model_retry_states.get(model)
                    )
                    old_probe_count = (
                        current_state.probe_success_count if current_state else 0
                    )

                    if await self._probe_model_recovery(
                        model, bypass_interval_check=True
                    ):
                        # Check if fully recovered
                        if not self._is_in_cooldown(model):
                            recovered = True
                            break
                        # Partial success, continue probing
                        continue
                    else:
                        # Check if we made progress (probe succeeded but didn't fully recover yet)
                        new_probe_count = (
                            current_state.probe_success_count if current_state else 0
                        )
                        if new_probe_count > old_probe_count:
                            # Partial progress made, continue probing
                            continue
                        else:
                            # Actual probe failed, stop trying
                            break

                if recovered:
                    # Model recovered, we can use it
                    pass
                else:
                    # Still in cooldown, skip to next model
                    continue

            # Try the model with retries
            is_fallback_model = False
            if fallback_model:
                if isinstance(fallback_model, list):
                    is_fallback_model = model in fallback_model
                else:
                    is_fallback_model = model == fallback_model

            fallback_recorded = False
            max_attempts_for_model = len(self._degradation_config.retry_delays) + 1
            if model == original_model and fallback_model:
                max_attempts_for_model = 1

            last_error = None
            for attempt in range(max_attempts_for_model):
                # Check per-request attempt limit (not global) to prevent premature exhaustion
                if request_attempts >= self._degradation_config.max_total_attempts:
                    self._graceful_metrics.record_duration(time.time() - start_time)
                    raise BackendError(
                        message="Maximum total attempts exceeded in graceful degradation",
                        code="max_attempts_exceeded",
                        status_code=429,
                    )

                request_attempts += 1
                self._graceful_metrics.record_attempt()
                if hasattr(self, "_total_attempts"):
                    with contextlib.suppress(Exception):
                        self._total_attempts += 1  # type: ignore[operator]

                state.attempts = attempt

                try:
                    # Calculate delay for this attempt with jitter
                    delay = calculate_retry_delay(
                        attempt, self._degradation_config.retry_delays
                    )

                    logger.info(
                        f"Retrying model {model} after {delay:.1f}s delay (attempt {attempt})"
                    )
                    self._graceful_metrics.record_wait(delay)
                    await asyncio.sleep(delay)

                    if is_fallback_model and not fallback_recorded:
                        self._graceful_metrics.record_fallback()
                        fallback_recorded = True

                    # Make the API call
                    # IMPORTANT: Always use non-streaming method for graceful degradation
                    # to prevent recursive 429 loops from streaming SSE processing
                    result = await self._chat_completions_code_assist(
                        request_data=request_data,
                        processed_messages=processed_messages,
                        effective_model=model,
                        _in_graceful_degradation=True,
                        **kwargs,
                    )
                    self._graceful_metrics.record_duration(time.time() - start_time)
                    return result

                except BackendError as e:
                    last_error = e
                    if not self._is_rate_limit_like_error(e):
                        self._graceful_metrics.record_duration(time.time() - start_time)
                        raise

                    if logger.isEnabledFor(logging.INFO):
                        if getattr(e, "code", None) == "empty_response":
                            logger.info(
                                "Model %s returned empty response on attempt %s",
                                model,
                                attempt + 1,
                            )
                        else:
                            logger.info(
                                f"Model {model} returned 429 on attempt {attempt + 1}"
                            )

                    # If this was our last attempt for this model, move to next model
                    if attempt >= max_attempts_for_model - 1:
                        logger.info(
                            f"Model {model} exhausted after {attempt + 1} attempts"
                        )
                        break

            # If we get here, all attempts for this model failed
            if model == original_model:
                # Original model failed, put it in cooldown
                retry_delay = (
                    self._extract_retry_delay(last_error) if last_error else None
                )
                self._set_cooldown(model, duration=retry_delay)

                if retry_delay:
                    logger.info(
                        "Model %s put in cooldown for %.1fs based on API response",
                        model,
                        retry_delay,
                    )

                # Start recovery probing task if enabled
                if self._degradation_config.enable_recovery_probing and (
                    self._recovery_probe_task is None
                    or self._recovery_probe_task.done()
                ):
                    self._recovery_probe_task = asyncio.create_task(
                        self._recovery_probing_loop()
                    )
            elif is_fallback_model:
                # Fallback model failed - put it in cooldown too
                retry_delay = (
                    self._extract_retry_delay(last_error) if last_error else None
                )
                self._set_cooldown(model, duration=retry_delay)

                if retry_delay:
                    logger.info(
                        "Fallback model %s put in cooldown for %.1fs based on API response",
                        model,
                        retry_delay,
                    )
                else:
                    logger.info("Fallback model %s exhausted, put in cooldown", model)

        # If we get here, all requested models failed
        # Mark quota exceeded but keep backend functional for other models
        self._graceful_metrics.record_duration(time.time() - start_time)
        self._mark_backend_unusable(reason="quota_exceeded")
        self._permanently_failed = True
        self.is_functional = False

        # If fallback is disabled, the error should reflect that all models are
        # considered exhausted because no fallback was attempted.
        if disable_fallback:
            error_code = "all_models_exhausted"
            error_message = "all models exhausted; fallback is disabled."
        else:
            error_code = "models_rate_limited"
            error_message = (
                "All models exhausted including fallbacks. Please try again later."
            )

        # Raise error to inform client about rate limiting
        raise BackendError(
            message=error_message,
            code=error_code,
            status_code=429,
        )

    async def _recovery_probing_loop(self) -> None:
        """Background task to probe for model recovery."""
        if not self._degradation_config.enable_recovery_probing:
            return

        sleep_fn = getattr(asyncio, "sleep", None)
        # When asyncio.sleep is monkeypatched (e.g., AsyncMock in tests), avoid
        # spinning a tight loop that starves the event loop.
        if sleep_fn and getattr(sleep_fn, "__module__", "") == "unittest.mock":
            return

        while True:
            try:
                await asyncio.sleep(self._degradation_config.recovery_probe_interval)

                # Check each model in cooldown
                models_in_cooldown = [
                    model
                    for model in self._model_retry_states
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
