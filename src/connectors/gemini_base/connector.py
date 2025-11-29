"""
Main connector class for Gemini OAuth Base.
"""

import abc
import asyncio
import contextlib
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Iterable
from pathlib import Path
from typing import Any, cast

import httpx
import requests  # type: ignore[import-untyped]
import tiktoken
from fastapi import HTTPException
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from src.connectors.gemini import GeminiBackend
from src.connectors.gemini_base.config import (
    CODE_ASSIST_PROMPT_LIMIT_MARGIN,
    DEFAULT_AVAILABLE_MODELS,
    DEFAULT_CODE_ASSIST_PROMPT_LIMIT,
    DEFAULT_READ_TIMEOUT,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
    ModelRetryState,
)
from src.connectors.gemini_base.credentials import (
    CLI_REFRESH_COMMAND,
    CLI_REFRESH_COOLDOWN_SECONDS,
    CLI_REFRESH_THRESHOLD_SECONDS,
    TOKEN_EXPIRY_BUFFER_SECONDS,
    TOKEN_REFRESH_MAX_WAIT_SECONDS,
    TOKEN_REFRESH_POLL_INTERVAL_SECONDS,
    GeminiPersonalCredentialsFileHandler,
)
from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin
from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    InvalidRequestError,
    ServiceUnavailableError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.gemini_metadata import (
    create_gemini_response_metadata,
)
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.security.loop_prevention import LOOP_GUARD_HEADER, LOOP_GUARD_VALUE
from src.core.services.translation_service import TranslationService

# Code Assist API endpoint (matching the CLI's endpoint):
#   https://cloudcode-pa.googleapis.com
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
# API version: v1internal
# Default model example: "codechat-bison"
# Default project for free tier used in UserTierId enum: "free-tier"

logger = logging.getLogger(__name__)

# Timeout configuration for streaming requests
# Connection timeout: time to establish connection
DEFAULT_CONNECTION_TIMEOUT = 60.0


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
    gemini_api_base_url: str | None = None

    # Server-side storage for Gemini thought_signatures.
    # Droid and similar clients don't preserve extra_content, so we store
    # the mapping of tool_call_id -> thought_signature server-side and
    # inject it when processing subsequent requests.
    # Key format: "session_id:tool_call_id" -> thought_signature
    _thought_signature_cache: dict[str, str] = {}

    @staticmethod
    def _normalize_model_key(model_name: str) -> str:
        """Normalize model identifiers for prompt-limit lookups."""
        normalized = (model_name or "").strip().lower()
        if ":" in normalized:
            normalized = normalized.split(":", 1)[-1]
        if normalized.startswith("models/"):
            normalized = normalized[len("models/") :]
        return normalized

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
                    if logger.isEnabledFor(logging.DEBUG):
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
            if logger.isEnabledFor(logging.WARNING):
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
        self._refresh_token: str | None = None
        self._token_refresh_lock = asyncio.Lock()
        self.translation_service = translation_service
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0
        self._pending_reload_task: asyncio.Future[Any] | None = None
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False
        self._last_cli_refresh_attempt = 0.0
        self._cli_refresh_process: subprocess.Popen[bytes] | None = None
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
        self._model_loading_task: asyncio.Task[Any] | None = None

        # Cache for fast model validation lookups
        self.available_models: list[str] = list(DEFAULT_AVAILABLE_MODELS)
        self._available_models_set: set[str] = set(self.available_models)
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
        # Debounce credentials reload events to avoid noisy filesystem churn
        self._last_reload_event_ts: float = 0.0
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
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate
            silent: If True, suppress INFO level logging

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Required fields for OAuth credentials
        required_fields = ["access_token"]
        for f in required_fields:
            if f not in credentials:
                errors.append(f"Missing required field: {f}")
            elif not isinstance(credentials[f], str) or not credentials[f]:
                errors.append(f"Invalid {f}: must be a non-empty string")

        # Optional refresh token validation
        if "refresh_token" in credentials and (
            not isinstance(credentials["refresh_token"], str)
            or not credentials["refresh_token"]
        ):
            errors.append("Invalid refresh_token: must be a non-empty string")

        # Expiry validation (if present)
        if "expiry_date" in credentials:
            expiry = credentials["expiry_date"]
            if not isinstance(expiry, int | float):
                errors.append("Invalid expiry_date: must be a number (ms)")
            else:
                # Record expired status without failing validation; refresh logic handles it
                import datetime

                current_utc_s = datetime.datetime.now(datetime.timezone.utc).timestamp()
                if (
                    current_utc_s >= float(expiry) / 1000.0
                    and not silent
                    and logger.isEnabledFor(logging.INFO)
                ):
                    logger.info(
                        "Loaded Gemini OAuth credentials appear expired; refresh will be triggered."
                    )

        return len(errors) == 0, errors

    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that the OAuth credentials file exists and is readable.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Use custom path if provided, otherwise default to ~/.gemini
        if self.gemini_cli_oauth_path:
            creds_path = Path(self.gemini_cli_oauth_path) / "oauth_creds.json"
        else:
            home_dir = Path.home()
            creds_path = home_dir / ".gemini" / "oauth_creds.json"

        if not creds_path.exists():
            errors.append(f"OAuth credentials file not found at {creds_path}")
            return False, errors

        if not creds_path.is_file():
            errors.append(
                f"OAuth credentials path exists but is not a file: {creds_path}"
            )
            return False, errors

        try:
            with open(creds_path, encoding="utf-8") as f:
                credentials = json.load(f)

            # Validate the loaded credentials
            is_valid, validation_errors = self._validate_credentials_structure(
                credentials
            )
            errors.extend(validation_errors)

            return is_valid, errors

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in credentials file: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"Permission denied reading credentials file: {creds_path}")
            return False, errors
        except Exception as e:
            errors.append(f"Unexpected error reading credentials file: {e}")
            return False, errors

    def _validate_active_credentials_path(self) -> tuple[bool, list[str]]:
        """Validate the currently used credentials path, if known.

        This avoids incorrectly validating a different credential source (e.g.,
        oauth_creds.json when a connector uses an alternate database file).
        """
        if self._credentials_path:
            errors: list[str] = []
            try:
                if not self._credentials_path.exists():
                    errors.append(
                        f"Credentials path not found: {self._credentials_path}"
                    )
                elif not self._credentials_path.is_file():
                    errors.append(
                        f"Credentials path exists but is not a file: {self._credentials_path}"
                    )
            except OSError as exc:
                errors.append(
                    f"Error accessing credentials path {self._credentials_path}: {exc}"
                )

            return len(errors) == 0, errors

        return self._validate_credentials_file_exists()

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

            # Extract details for retry delay parsing
            details = {}
            if isinstance(error_detail, dict):
                details = error_detail
            elif isinstance(error_detail, list) and len(error_detail) > 0:
                # Handle list format seen in logs: [{'error': ...}]
                first_item = error_detail[0]
                if isinstance(first_item, dict):
                    details = first_item

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
                    details=details,
                )

            raise BackendError(
                message=f"Code Assist API streaming error: {error_detail}",
                code="code_assist_error",
                status_code=response.status_code,
                details=details,
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
        prompt_text_parts: list[str] = []
        try:
            encoding = tiktoken.get_encoding("cl100k_base")

            def _serialize_part(part: Any) -> str | None:
                if isinstance(part, dict):
                    text_value = part.get("text")
                    if isinstance(text_value, str):
                        return text_value
                    try:
                        return json.dumps(part, ensure_ascii=False, default=str)
                    except Exception:
                        return repr(part)
                if isinstance(part, str | bytes):
                    return (
                        part.decode("utf-8", "ignore")
                        if isinstance(part, bytes)
                        else part
                    )
                if part is None:
                    return None
                return str(part)

            system_instruction = code_assist_request.get("systemInstruction")
            if isinstance(system_instruction, dict):
                for part in system_instruction.get("parts", []):
                    serialized = _serialize_part(part)
                    if serialized:
                        prompt_text_parts.append(serialized)

            for content in code_assist_request.get("contents", []):
                if not isinstance(content, dict):
                    continue
                for part in content.get("parts", []):
                    serialized = _serialize_part(part)
                    if serialized:
                        prompt_text_parts.append(serialized)

            generation_config = code_assist_request.get("generationConfig")
            if generation_config:
                try:
                    prompt_text_parts.append(
                        json.dumps(generation_config, ensure_ascii=False)
                    )
                except Exception:
                    prompt_text_parts.append(repr(generation_config))

            for extra_key in ("tools", "toolConfig", "safetySettings"):
                extra_value = code_assist_request.get(extra_key)
                if extra_value:
                    try:
                        prompt_text_parts.append(
                            json.dumps(extra_value, ensure_ascii=False)
                        )
                    except Exception:
                        prompt_text_parts.append(repr(extra_value))

            if not prompt_text_parts:
                return 0

            full_prompt = "\n".join(prompt_text_parts)
            return len(encoding.encode(full_prompt))
        except Exception as exc:  # pragma: no cover - defensive logging only
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Failed to estimate prompt tokens: %s", exc)
            return None

    def _get_prompt_limit(self, effective_model: str) -> int | None:
        """Resolve the prompt-size threshold for the given model."""
        normalized = self._normalize_model_key(effective_model)

        limit = self._prompt_limit_overrides.get(normalized)

        if limit is None:
            for prefix, candidate_limit in self._prompt_limit_prefix_overrides:
                if normalized.startswith(prefix):
                    limit = candidate_limit
                    break

        if limit is None:
            limit = self._default_prompt_limit

        override_limit = getattr(self.config, "context_window_override", None)
        if isinstance(override_limit, int) and override_limit > 0:
            if limit is None:
                limit = override_limit
            else:
                limit = min(limit, override_limit)

        if limit is None or limit <= 0:
            return None

        return int(limit)

    def _enforce_prompt_limit(
        self,
        prompt_tokens: int | None,
        effective_model: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Prevent Code Assist requests that would exceed the plan allowance."""
        if prompt_tokens is None:
            return

        limit = self._get_prompt_limit(effective_model)
        if limit is None:
            return

        soft_limit = int(limit * CODE_ASSIST_PROMPT_LIMIT_MARGIN)
        if prompt_tokens <= soft_limit:
            return

        message = (
            "Estimated prompt size exceeds the Code Assist plan allowance. "
            "Please compress the conversation history or trim the request."
        )
        details = {
            "model": effective_model,
            "estimated_tokens": prompt_tokens,
            "limit": limit,
            "status": "CONTEXT_WINDOW_WILL_OVERFLOW",
            "advice": (
                "Use /compress or start a new session to reduce history size before retrying."
            ),
        }
        if request_id:
            details["request_id"] = request_id

        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Code Assist prompt blocked locally: estimated_tokens=%s limit=%s model=%s",
                prompt_tokens,
                limit,
                effective_model,
            )
        raise InvalidRequestError(
            message=message,
            details=details,
            code="context_window_will_overflow",
        )

    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if not self._credentials_path or self._file_observer:
            return

        try:
            event_handler = GeminiPersonalCredentialsFileHandler(self)
            self._file_observer = Observer()
            # Watch the parent directory of the credentials file
            watch_dir = self._credentials_path.parent
            self._file_observer.schedule(event_handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Started watching credentials file: {self._credentials_path}"
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to start file watching: {e}")

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file."""
        observer = self._file_observer
        if observer:
            try:
                if observer.is_alive():
                    observer.stop()
                    # Only join if we're not in the observer thread to avoid "cannot join current thread" error
                    current_thread = threading.current_thread()
                    if (
                        hasattr(observer, "_thread")
                        and observer._thread != current_thread
                    ):
                        observer.join()
                self._file_observer = None
                logger.info("Stopped watching credentials file")
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(f"Error stopping file watcher: {e}")

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload when the credentials file changes."""
        now = time.time()
        # Drop duplicate events that happen too frequently (e.g., editor/temp-file noise)
        if now - self._last_reload_event_ts < 5.0:
            return
        self._last_reload_event_ts = now

        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return
            if self._reload_scheduling_in_progress:
                return
            self._reload_scheduling_in_progress = True

        async def reload_task() -> None:
            await self._handle_credentials_file_change()

        loop = self._main_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            self._main_loop = loop

        if loop is None:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Cannot schedule credentials reload: no running event loop available."
                )
            with self._reload_task_lock:
                self._reload_scheduling_in_progress = False
            return

        if loop.is_closed():
            logger.debug(
                "Skipping credentials reload scheduling: event loop is closed. Stopping file watcher."
            )
            self._stop_file_watching()
            self._main_loop = None
            with self._reload_task_lock:
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with self._reload_task_lock:
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with self._reload_task_lock:
                self._pending_reload_task = task
                self._reload_scheduling_in_progress = False

        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        if running_loop is loop:
            task = loop.create_task(reload_task())
            _assign_task(task)
            return

        def schedule_task() -> None:
            try:
                task = loop.create_task(reload_task())
                _assign_task(task)
            except Exception as exc:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Failed to schedule credentials reload: %s", exc)
                with self._reload_task_lock:
                    self._reload_scheduling_in_progress = False

        try:
            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.debug(
                "Event loop unavailable for credentials reload scheduling: %s",
                exc,
            )
            self._stop_file_watching()
            self._main_loop = None
            with self._reload_task_lock:
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False

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
                    if logger.isEnabledFor(logging.INFO):
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
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Credentials file reload completed but token is still invalid"
                        )
            else:
                self._degrade(["Failed to reload credentials after file change"])
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Failed to reload credentials after file change")

        except Exception as e:
            self._degrade([f"Error handling credentials file change: {e}"])
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error handling credentials file change: {e}", exc_info=True
                )
        finally:
            if success:
                self._last_credentials_event_hash = self._credentials_file_hash
            else:
                self._last_credentials_event_hash = None

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

    def _get_available_models_set(self) -> set[str]:
        """Get the cached set of available models for fast lookups.

        Returns:
            set[str]: Set of available model names
        """
        if not self._available_models_set:
            self._available_models_set = set(self.available_models or [])
        return self._available_models_set

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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Request error connecting to Gemini OAuth API: %s", e, exc_info=True
                )
            raise ServiceUnavailableError(
                message=f"Could not connect to Gemini OAuth API ({e})"
            )

    def _get_session_headers(self) -> dict[str, str]:
        """Get headers for authorized session."""
        return self._get_api_headers()

    def _compute_credentials_fingerprint(self, credentials: dict[str, Any]) -> str:
        """Compute a fingerprint of the credentials to detect changes."""
        # Use key fields that affect authentication
        key_fields = [
            credentials.get("access_token", ""),
            credentials.get("refresh_token", ""),
            str(credentials.get("expiry_date", "")),
        ]
        return hashlib.sha256("|".join(key_fields).encode("utf-8")).hexdigest()

    async def _load_oauth_credentials(
        self, force_reload: bool = False, silent: bool = False
    ) -> bool:
        """Load OAuth credentials from oauth_creds.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged
            silent: If True, suppress INFO level logging (used when checking for changes)

        Returns:
            bool: True if credentials loaded successfully, False otherwise
        """
        try:
            # Use custom path if provided, otherwise default to ~/.gemini
            if self.gemini_cli_oauth_path:
                creds_path = Path(self.gemini_cli_oauth_path) / "oauth_creds.json"
            else:
                home_dir = Path.home()
                creds_path = home_dir / ".gemini" / "oauth_creds.json"
            self._credentials_path = creds_path

            if not creds_path.exists():
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        f"Gemini OAuth credentials not found at {creds_path}"
                    )
                return False

            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    current_modified = creds_path.stat().st_mtime
                    if (
                        current_modified == self._last_modified
                        and self._oauth_credentials
                    ):
                        # File hasn't changed and credentials are in memory, no need to reload
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Gemini OAuth credentials file not modified, using cached."
                            )
                        return True
                except OSError:
                    # If cannot get file stats, proceed with reading
                    pass

            # Update last modified time
            try:
                current_modified = creds_path.stat().st_mtime
                self._last_modified = current_modified
            except OSError:
                pass

            raw_text = creds_path.read_text(encoding="utf-8")
            credentials = json.loads(raw_text)

            # Validate essential fields
            if "access_token" not in credentials:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Malformed Gemini OAuth credentials: missing access_token"
                    )
                return False

            self._oauth_credentials = credentials
            self._credentials_fingerprint = self._compute_credentials_fingerprint(
                credentials
            )
            self._credentials_file_hash = hashlib.sha256(
                raw_text.encode("utf-8", "ignore")
            ).hexdigest()
            self._last_credentials_event_hash = self._credentials_file_hash
            if not silent and logger.isEnabledFor(logging.INFO):
                log_msg = "Successfully loaded Gemini OAuth credentials"
                if force_reload:
                    log_msg += " (force reload)"
                logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error(
                f"Error decoding Gemini OAuth credentials JSON: {e}",
                exc_info=True,
            )
            return False
        except OSError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error loading Gemini OAuth credentials: {e}", exc_info=True
                )
            return False

    def _is_token_expired(self) -> bool:
        """Check if the current access token is expired or about to expire."""
        if not self._oauth_credentials:
            return True

        expiry_ms = self._oauth_credentials.get("expiry_date")
        if not expiry_ms:
            # If no expiry date, assume valid (or handle as needed)
            return False

        # Convert expiry to seconds
        expiry_time = float(expiry_ms) / 1000.0
        current_time = time.time()

        # Check if expired with buffer
        return current_time >= (expiry_time - TOKEN_EXPIRY_BUFFER_SECONDS)

    def _seconds_until_token_expiry(self) -> float | None:
        """Get the number of seconds until the current token expires.

        Returns:
            float: Seconds remaining until expiry (can be negative if expired)
            None: If no credentials or no expiry date available
        """
        if not self._oauth_credentials:
            return None

        expiry_ms = self._oauth_credentials.get("expiry_date")
        if not expiry_ms:
            return None

        # Convert expiry to seconds
        expiry_time = float(expiry_ms) / 1000.0
        current_time = time.time()
        return expiry_time - current_time

    def _should_trigger_cli_refresh(self) -> bool:
        """Check if we should proactively trigger a CLI refresh."""
        if not self._oauth_credentials:
            return True

        expiry_ms = self._oauth_credentials.get("expiry_date")
        if not expiry_ms:
            return False

        expiry_time = float(expiry_ms) / 1000.0
        current_time = time.time()

        # Trigger refresh if within threshold window
        return current_time >= (expiry_time - CLI_REFRESH_THRESHOLD_SECONDS)

    def _launch_cli_refresh_process(self) -> None:
        """Launch the Gemini CLI in the background to refresh credentials."""
        now = time.time()
        if now - self._last_cli_refresh_attempt < CLI_REFRESH_COOLDOWN_SECONDS:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Skipping CLI refresh due to cooldown")
            return

        # Check if process is already running
        if self._cli_refresh_process and self._cli_refresh_process.poll() is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("CLI refresh process already running")
            return

        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Launching Gemini CLI to refresh credentials...")

            # Use creationflags to hide the window on Windows
            creationflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW  # type: ignore

            cmd = list(CLI_REFRESH_COMMAND)
            # On Windows, we need to resolve the executable path to avoid using shell=True
            if sys.platform == "win32" and cmd:
                executable = shutil.which(cmd[0])
                if executable:
                    cmd[0] = executable

            self._cli_refresh_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,  # Provide stdin to avoid hanging if it asks for input
                shell=False,
                creationflags=creationflags,
            )
            self._last_cli_refresh_attempt = now

        except Exception as e:
            logger.error(f"Failed to launch Gemini CLI refresh: {e}")

    async def _poll_for_new_token(self) -> bool:
        """Poll for a new valid token after launching refresh."""
        start_time = time.time()
        while time.time() - start_time < TOKEN_REFRESH_MAX_WAIT_SECONDS:
            # Force reload from file
            if (
                await self._load_oauth_credentials(force_reload=True, silent=True)
                and not self._is_token_expired()
            ):
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Successfully picked up new token from CLI refresh")
                return True

            await asyncio.sleep(TOKEN_REFRESH_POLL_INTERVAL_SECONDS)

        return False

    async def _refresh_token_if_needed(self) -> bool:
        """Ensure a valid access token is available, refreshing when necessary."""
        if not self._oauth_credentials:
            await self._load_oauth_credentials()

        if not self._oauth_credentials:
            return False

        expired = self._is_token_expired()
        near_expiry = self._should_trigger_cli_refresh()

        if not expired and not near_expiry:
            return True

        async with self._token_refresh_lock:
            if not self._oauth_credentials:
                await self._load_oauth_credentials()

            if not self._oauth_credentials:
                return False

            expired = self._is_token_expired()
            near_expiry = self._should_trigger_cli_refresh()

            if not expired and near_expiry:
                self._launch_cli_refresh_process()
                return True

            if not expired:
                return True

            logger.info(
                "Access token expired; reloading credentials and invoking CLI refresh if needed."
            )

            reloaded = await self._load_oauth_credentials()
            if reloaded and not self._is_token_expired():
                if self._should_trigger_cli_refresh():
                    self._launch_cli_refresh_process()
                return True

            self._launch_cli_refresh_process()

            refreshed = await self._poll_for_new_token()
            if refreshed:
                return True

            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Automatic Gemini CLI refresh did not produce a valid token in time."
                )
            return False

    async def _validate_runtime_credentials(self) -> bool:
        """Validate credentials at runtime before making a request.

        This checks if we have loaded credentials and if the token is valid.
        If not, it attempts to reload/refresh.

        Returns:
            bool: True if credentials are valid, False otherwise
        """
        # Clear previous errors
        self._credential_validation_errors = []

        # Ensure we have credentials loaded
        if not self._oauth_credentials and not await self._load_oauth_credentials():
            self._credential_validation_errors.append(
                "No OAuth credentials loaded and failed to load from file"
            )
            return False

        # Check expiry
        if self._is_token_expired() and not await self._refresh_token_if_needed():
            self._credential_validation_errors.append(
                "Access token expired and failed to refresh"
            )
            return False

        return True

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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Health check failed - backend error: {e}", exc_info=True)
            return False
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Health check failed - unexpected error: {e}", exc_info=True
                )
            return False

    async def _ensure_healthy(self) -> None:
        """Perform health check to ensure backend is functional."""
        if not self._health_checked:
            return

        # Simple check: do we have a valid token?
        if not await self._perform_health_check():
            raise BackendError(
                message="Backend health check failed: Invalid credentials",
                code="health_check_failed",
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
            self.available_models = list(DEFAULT_AVAILABLE_MODELS)
            # Build the set cache from the fallback list
            self._available_models_set = set(self.available_models)
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    f"Loaded {len(self.available_models)} known Code Assist models (hardcoded fallback)"
                )

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to reach fetchAvailableModels endpoint %s: %s", url, exc
                )
            return

        if response.status_code != 200:
            if logger.isEnabledFor(logging.DEBUG):
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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to decode fetchAvailableModels response from %s: %s",
                    url,
                    exc,
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
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Loaded %d models from fetchAvailableModels endpoint",
                    len(self.available_models),
                )

    async def initialize(self, **kwargs: Any) -> None:
        """Initialize the connector."""
        try:
            # Set custom path if configured
            self.gemini_cli_oauth_path = self.config.get("gemini_cli_oauth_path")

            # Initial load of credentials
            await self._load_oauth_credentials()

            # Start file watcher
            self._start_file_watching()

            # Validate initial state
            is_valid, errors = self._validate_credentials_file_exists()
            if not is_valid:
                self._fail_init(errors)
                logger.warning(
                    f"Gemini OAuth connector {self.name} initialized with errors: {'; '.join(errors)}"
                )
            else:
                self.is_functional = True
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        f"Gemini OAuth connector {self.name} initialized successfully"
                    )

            # Try to load models (non-blocking)
            if self.is_functional:
                self._model_loading_task = asyncio.create_task(
                    self._ensure_models_loaded()
                )

        except Exception as e:
            self._fail_init([f"Initialization error: {e!s}"])
            logger.error(
                f"Failed to initialize Gemini OAuth connector {self.name}: {e}",
                exc_info=True,
            )

    def _get_api_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        if not self._oauth_credentials:
            return {}

        token = self._oauth_credentials.get("access_token", "")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Gemini-OAuth-Connector/1.0",
        }

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
                if getattr(
                    e, "status_code", 0
                ) == 429 or self._is_rate_limit_like_error(e):
                    return await self._handle_429_with_graceful_degradation(
                        original_model=model_name,
                        request_data=request_data,
                        processed_messages=processed_messages,
                        **kwargs,
                    )
                raise

        except Exception as e:
            if isinstance(e, HTTPException):
                raise

            # Wrap other exceptions in BackendError
            logger.error(f"Error in chat_completions: {e}", exc_info=True)
            raise BackendError(
                message=f"Gemini OAuth error: {e!s}",
                code="gemini_oauth_error",
                status_code=500,
            )

    async def _chat_completions_code_assist(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _in_graceful_degradation: bool = False,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        """Handle non-streaming chat completions using Code Assist API."""
        # Convert request to Code Assist format
        code_assist_request = self._convert_to_code_assist_format(
            request_data, processed_messages, effective_model
        )

        # Estimate tokens and enforce limit
        if not _in_graceful_degradation:
            prompt_tokens = self._estimate_prompt_tokens(code_assist_request)
            request_id = getattr(request_data, "request_id", None)
            self._enforce_prompt_limit(
                prompt_tokens, effective_model, request_id=request_id
            )

        # Prepare headers
        headers = self._get_api_headers()

        # Add loop prevention header
        headers[LOOP_GUARD_HEADER] = LOOP_GUARD_VALUE

        # Use the generateContent endpoint
        url = f"{CODE_ASSIST_ENDPOINT}/v1internal/projects/free-tier/locations/global/publishers/google/models/{effective_model}:generateContent"

        try:
            # Make the API call
            response = await self.client.post(
                url,
                headers=headers,
                json=code_assist_request,
                timeout=DEFAULT_READ_TIMEOUT,
            )

            # Handle errors
            if response.status_code != 200:
                try:
                    error_data = response.json()
                except Exception:
                    error_data = {"error": response.text}

                # Check for rate limiting
                if response.status_code == 429:
                    raise BackendError(
                        message="Rate limit exceeded",
                        code="rate_limit_exceeded",
                        status_code=429,
                        details=error_data,
                    )

                raise BackendError(
                    message=f"Code Assist API error: {response.status_code}",
                    code="code_assist_error",
                    status_code=response.status_code,
                    details=error_data,
                )

            # Process response
            response_data = response.json()

            # Convert back to OpenAI format
            openai_response = self._convert_from_code_assist_format(
                response_data, effective_model
            )

            # Create response envelope
            return ResponseEnvelope(
                content=openai_response,
                headers=dict(response.headers),
                status_code=200,
            )

        except httpx.TimeoutException:
            raise BackendError(
                message="Request timed out",
                code="timeout",
                status_code=504,
            )
        except Exception as e:
            if isinstance(e, BackendError):
                raise
            logger.error(f"Error in _chat_completions_code_assist: {e}", exc_info=True)
            raise BackendError(
                message=f"Unexpected error: {e!s}",
                code="internal_error",
                status_code=500,
            )

    async def _chat_completions_code_assist_streaming(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        _in_graceful_degradation: bool = False,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        """Handle streaming chat completions using Code Assist API."""
        # Convert request to Code Assist format
        code_assist_request = self._convert_to_code_assist_format(
            request_data, processed_messages, effective_model
        )

        # Estimate tokens and enforce limit
        # Note: For streaming, we enforce the limit before starting the stream
        if not _in_graceful_degradation:
            prompt_tokens = self._estimate_prompt_tokens(code_assist_request)
            request_id = getattr(request_data, "request_id", None)
            self._enforce_prompt_limit(
                prompt_tokens, effective_model, request_id=request_id
            )
        else:
            prompt_tokens = 0

        # Prepare headers
        headers = self._get_api_headers()

        # Add loop prevention header
        headers[LOOP_GUARD_HEADER] = LOOP_GUARD_VALUE

        # Use the streamGenerateContent endpoint
        url = f"{CODE_ASSIST_ENDPOINT}/v1internal/projects/free-tier/locations/global/publishers/google/models/{effective_model}:streamGenerateContent"

        # Prepare for streaming
        encoding = tiktoken.get_encoding("cl100k_base")
        generated_text = ""
        error_json_buffer: str | None = None

        async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
            nonlocal generated_text, error_json_buffer
            response = None

            # Helper to skip empty chunks
            def _should_skip_chunk(chunk: dict[str, Any]) -> bool:
                choices = chunk.get("choices", [])
                if not choices:
                    return True
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                # Skip if content is empty string (but not None)
                # and no other fields like tool_calls are present
                return bool(
                    content == ""
                    and not delta.get("tool_calls")
                    and not choices[0].get("finish_reason")
                )

            try:
                # Initiate streaming request
                response = await self.client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=code_assist_request,
                    timeout=DEFAULT_CONNECTION_TIMEOUT,
                ).__aenter__()

                if response.status_code != 200:
                    # Handle immediate errors
                    error_content = await response.aread()
                    try:
                        error_data = json.loads(error_content)
                    except Exception:
                        error_data = {"error": error_content.decode("utf-8", "ignore")}

                    # Check for rate limiting
                    if response.status_code == 429:
                        raise BackendError(
                            message="Rate limit exceeded",
                            code="rate_limit_exceeded",
                            status_code=429,
                            details=error_data,
                        )

                    raise BackendError(
                        message=f"Code Assist API error: {response.status_code}",
                        code="code_assist_error",
                        status_code=response.status_code,
                        details=error_data,
                    )

                # Process the stream
                chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
                created = int(time.time())

                # Helper to build error chunk
                def _build_error_chunk(
                    msg: str, code: int = 500, error_type: str = "api_error"
                ) -> dict[str, Any]:
                    return {
                        "id": chunk_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": effective_model,
                        "choices": [
                            {"index": 0, "delta": {}, "finish_reason": "error"}
                        ],
                        "error": {
                            "message": msg,
                            "type": error_type,
                            "code": code,
                        },
                    }

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
                                            error_info = parsed_error.get("error") or {}
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
                                                    "created": error_chunk["created"],
                                                },
                                            )
                                            done = True
                                            return
                                        else:
                                            error_json_buffer = None

                        metadata = create_gemini_response_metadata(
                            model="gemini-oauth",
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
                                "raw_finish_reason": domain_chunk.get("choices", [{}])[
                                    0
                                ].get("finish_reason"),
                            }
                        )

                        # Store thought_signatures server-side for clients that don't preserve extra_content
                        # (e.g., Droid). This allows us to inject signatures in subsequent requests.
                        if raw_tool_calls and isinstance(raw_tool_calls, list):
                            session_id = getattr(request_data, "session_id", None) or ""
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
                                            (session_id[:8] if session_id else "none"),
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
                    async for chunk in response.aiter_bytes(chunk_size=4096):
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

                            for processed_chunk in _process_decoded_line(decoded_line):
                                # Check if this chunk signals the end of the stream
                                # If so, buffer it and yield it AFTER usage
                                content = processed_chunk.content
                                is_stop_chunk = False

                                if isinstance(content, dict):
                                    choices = content.get("choices", [])
                                    if choices and isinstance(choices[0], dict):
                                        finish_reason = choices[0].get("finish_reason")
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
                                    logger.debug("[STREAMING] Buffering stop chunk")
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
                                logger.debug(
                                    "[STREAMING] Buffering stop chunk (from buffer)"
                                )
                                final_stop_chunk = processed_chunk
                                continue

                            yield processed_chunk
                            # Yield control to the event loop
                            await asyncio.sleep(0)
                        line_buffer = ""

                    logger.debug(
                        f"[STREAMING] Completed chunk loop. final_stop_chunk captured: {final_stop_chunk is not None}"
                    )

                except GeneratorExit:
                    logger.debug("Stream closed by consumer before completion")
                    raise
                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
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
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"[STREAMING] Calculated usage: {usage}")
                except Exception as e:
                    logger.warning(
                        f"Could not calculate completion tokens for streaming: {e}"
                    )

                # Yield the final stop chunk with usage merged in
                # Import the protective wrapper to detect accidental stringification
                from src.core.ports.streaming_contracts import StopChunkWithUsage

                if final_stop_chunk:
                    logger.debug("[STREAMING] Yielding final stop chunk with usage")
                    # Merge usage into the final stop chunk content
                    final_content = final_stop_chunk.content
                    if isinstance(final_content, dict) and usage:
                        final_content = dict(final_content)  # Copy to avoid mutation
                        final_content["usage"] = usage
                        # Wrap with StopChunkWithUsage to detect accidental
                        # stringification. If any code tries to str() this dict,
                        # it will raise UsageChunkLeakError with a stack trace.
                        final_content = StopChunkWithUsage(final_content)
                        # Log StopChunkWithUsage creation at DEBUG level
                        logger.debug(
                            "[STREAMING] Created StopChunkWithUsage: "
                            "chunk_id=%s, usage=%s",
                            final_content.get("id", "unknown"),
                            usage,
                        )
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
                    # Merge usage into the generic stop chunk
                    if isinstance(final_chunk, dict) and usage:
                        final_chunk["usage"] = usage
                        # Wrap with protective class
                        final_chunk = StopChunkWithUsage(final_chunk)
                        # Log StopChunkWithUsage creation at DEBUG level
                        logger.debug(
                            "[STREAMING] Created StopChunkWithUsage (fallback): "
                            "chunk_id=%s, usage=%s",
                            final_chunk.get("id", "unknown"),
                            usage,
                        )
                    yield ProcessedResponse(content=final_chunk, usage=usage)

            except BackendError as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                raise
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                # Build proper error chunk with full error details
                now = int(time.time())
                error_message = str(e) if str(e) else "An unexpected error occurred"
                error_chunk = {
                    "id": f"chatcmpl-error-{now}",
                    "object": "chat.completion.chunk",
                    "created": now,
                    "model": effective_model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
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

        try:
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
            raise

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
        self, envelope: ResponseEnvelope
    ) -> ProcessedResponse:
        """Convert a ResponseEnvelope to a ProcessedResponse stream chunk."""
        # This is used when we fall back to non-streaming for a streaming request
        # (e.g. during graceful degradation)
        content = envelope.content
        if isinstance(content, dict):
            # Ensure it looks like a stream chunk
            if "object" not in content:
                content["object"] = "chat.completion.chunk"

            choices = content.get("choices", [])
            if choices and isinstance(choices[0], dict):
                choice = choices[0]
                # If it has 'message', move content to 'delta'
                if "message" in choice and "delta" not in choice:
                    choice["delta"] = choice.pop("message")

                # Ensure finish_reason is present
                if "finish_reason" not in choice:
                    choice["finish_reason"] = "stop"

        return ProcessedResponse(
            content=content,
            metadata=envelope.metadata,
            usage=getattr(envelope, "usage", None),
        )

    def _generate_user_prompt_id(self, request_data: Any = None) -> str:
        """Generate a unique ID for the user prompt."""
        return str(uuid.uuid4())

    def _convert_to_code_assist_format(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        """Convert OpenAI-format request to Code Assist format."""
        # Extract messages
        messages = []
        system_instruction = None

        for msg in processed_messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                # Code Assist supports system instructions
                if system_instruction is None:
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    # Append to existing system instruction
                    system_instruction["parts"].append({"text": content})
            elif role == "user":
                messages.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                messages.append({"role": "model", "parts": [{"text": content}]})

        # Build the request body
        body: dict[str, Any] = {
            "contents": messages,
            "generationConfig": self._build_generation_config(request_data),
        }

        if system_instruction:
            body["systemInstruction"] = system_instruction

        # Add safety settings (disable blocking)
        body["safetySettings"] = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_NONE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_NONE",
            },
        ]

        return body

    def _build_generation_config(self, request_data: Any) -> dict[str, Any]:
        """Build the generation config from request data."""
        config: dict[str, Any] = {}

        # Map OpenAI parameters to Gemini parameters
        if hasattr(request_data, "temperature"):
            config["temperature"] = request_data.temperature

        if hasattr(request_data, "max_tokens"):
            config["maxOutputTokens"] = request_data.max_tokens

        if hasattr(request_data, "top_p"):
            config["topP"] = request_data.top_p

        if hasattr(request_data, "stop"):
            stop_sequences = request_data.stop
            if isinstance(stop_sequences, str):
                config["stopSequences"] = [stop_sequences]
            elif isinstance(stop_sequences, list):
                config["stopSequences"] = stop_sequences

        # Set candidate count to 1 as we don't support n > 1
        config["candidateCount"] = 1

        return config

    def _convert_from_code_assist_format(
        self, response_data: dict[str, Any], model: str
    ) -> dict[str, Any]:
        """Convert Code Assist response to OpenAI format."""
        candidates = response_data.get("candidates", [])
        choices = []

        for i, candidate in enumerate(candidates):
            content_parts = candidate.get("content", {}).get("parts", [])
            text_content = ""
            for part in content_parts:
                if "text" in part:
                    text_content += part["text"]

            finish_reason = candidate.get("finishReason", "").lower()
            if finish_reason == "stop":
                finish_reason = "stop"
            elif finish_reason == "max_tokens":
                finish_reason = "length"
            elif finish_reason == "safety":
                finish_reason = "content_filter"
            else:
                finish_reason = "stop"  # Default

            choices.append(
                {
                    "index": i,
                    "message": {
                        "role": "assistant",
                        "content": text_content,
                    },
                    "finish_reason": finish_reason,
                }
            )

        usage = response_data.get("usageMetadata", {})
        openai_usage = {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": choices,
            "usage": openai_usage,
        }

    def _get_fallback_model(self, model: str) -> str | None:
        """Get a fallback model for the given model if configured."""
        # Check specific overrides first
        if model in self._degradation_config.model_fallbacks:
            return self._degradation_config.model_fallbacks[model]

        # Check generic fallback
        return self._degradation_config.generic_fallback_model

    def _is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown."""
        if model not in self._model_retry_states:
            return False

        state = self._model_retry_states[model]
        if state.cooldown_until is None:
            return False

        return time.time() < state.cooldown_until

    def _set_cooldown(self, model: str, delay: float) -> None:
        """Set cooldown for a model."""
        if model not in self._model_retry_states:
            self._model_retry_states[model] = ModelRetryState(model_name=model)

        state = self._model_retry_states[model]
        state.cooldown_until = time.time() + delay
        state.failure_count += 1
        state.last_failure_time = time.time()

        logger.warning(
            f"Model {model} placed in cooldown for {delay:.1f}s (failures: {state.failure_count})"
        )

    def _is_rate_limit_like_error(self, error: Exception) -> bool:
        """Check if an error looks like a rate limit error."""
        error_str = str(error).lower()
        if "429" in error_str:
            return True
        if "resource_exhausted" in error_str:
            return True
        if "quota" in error_str and "exceeded" in error_str:
            return True
        return "rate limit" in error_str

    def _extract_retry_delay_from_error(self, error: Exception) -> float | None:
        """Extract retry delay from error details if available."""
        # Try to find retry-after header or similar info
        # This is backend-specific, but we can look for common patterns
        if hasattr(error, "details") and isinstance(error.details, dict):  # type: ignore
            details = error.details  # type: ignore
            # Check for google.rpc.RetryInfo
            for detail in details.get("details", []):
                if "retryDelay" in detail:
                    delay_str = detail["retryDelay"]
                    if isinstance(delay_str, str) and delay_str.endswith("s"):
                        try:
                            return float(delay_str[:-1])
                        except ValueError:
                            pass
        return None

    async def _probe_model_recovery(self, model: str) -> bool:
        """Probe a model to see if it has recovered."""
        # Simple probe: list models or make a cheap call
        # For now, we assume if cooldown is over, we can try.
        # A more sophisticated probe would try a dummy generation.
        try:
            # We can try to generate a single token
            headers = self._get_api_headers()
            url = f"{CODE_ASSIST_ENDPOINT}/v1internal/projects/free-tier/locations/global/publishers/google/models/{model}:generateContent"

            body = {
                "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
                "generationConfig": {"maxOutputTokens": 1},
            }

            response = await self.client.post(
                url, headers=headers, json=body, timeout=5.0
            )

            return response.status_code == 200
        except Exception:
            return False

    async def _handle_429_with_graceful_degradation(
        self,
        original_model: str,
        request_data: Any,
        processed_messages: list[Any],
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Handle 429 errors by falling back to another model."""
        # 1. Record failure and set cooldown
        # Default delay if not extracted
        delay = self._degradation_config.base_cooldown_seconds
        # Exponential backoff based on failure count
        state = self._model_retry_states.get(original_model)
        if state:
            delay *= self._degradation_config.cooldown_multiplier**state.failure_count

        # Cap delay
        delay = min(delay, self._degradation_config.max_cooldown_seconds)

        self._set_cooldown(original_model, delay)

        # 2. Find fallback
        fallback_model = self._get_fallback_model(original_model)

        if not fallback_model:
            # No fallback, re-raise
            raise BackendError(
                message=f"Rate limit exceeded for {original_model} and no fallback available",
                code="rate_limit_exceeded",
                status_code=429,
            )

        if fallback_model == original_model:
            # Fallback is same as original (should not happen if configured correctly)
            raise BackendError(
                message=f"Rate limit exceeded for {original_model} (fallback loop)",
                code="rate_limit_exceeded",
                status_code=429,
            )

        logger.info(f"Gracefully degrading from {original_model} to {fallback_model}")

        # 3. Retry with fallback
        # We need to update request_data to use fallback model?
        # Actually chat_completions takes effective_model argument.
        # We can just call chat_completions recursively with new model.

        # Mark as in degradation to avoid double counting prompt tokens?
        # Or maybe we should count them for the fallback model.

        return await self.chat_completions(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=fallback_model,
            _in_graceful_degradation=True,
            **kwargs,
        )

    async def _recovery_probing_loop(self) -> None:
        """Background loop to probe failed models for recovery."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = time.time()
                for model, state in list(self._model_retry_states.items()):
                    if state.cooldown_until and now > state.cooldown_until:
                        # Cooldown over, probe
                        if await self._probe_model_recovery(model):
                            logger.info(f"Model {model} recovered from rate limiting")
                            del self._model_retry_states[model]
                        else:
                            # Still failing, extend cooldown
                            self._set_cooldown(model, 60)  # Add 1 minute

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in recovery probing loop: {e}")

    async def _discover_project_id(self, auth_session: Any = None) -> str | None:
        """Discover the project ID (not used for personal OAuth)."""
        return None

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to the file."""
        if not self._credentials_path:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Cannot save credentials: path not set")
            return

        try:
            content = json.dumps(credentials, indent=2)
            # Update hash to avoid reload loop
            self._credentials_file_hash = hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
            self._credentials_fingerprint = self._compute_credentials_fingerprint(
                credentials
            )

            # Write to file
            self._credentials_path.write_text(content, encoding="utf-8")

            # Update timestamp to avoid immediate reload
            with contextlib.suppress(OSError):
                self._last_modified = self._credentials_path.stat().st_mtime

            if logger.isEnabledFor(logging.INFO):
                logger.info("Saved updated OAuth credentials to file")

        except Exception as e:
            logger.error(f"Failed to save credentials: {e}", exc_info=True)

    def __del__(self) -> None:
        """Cleanup resources."""
        self._stop_file_watching()
        if self._recovery_probe_task:
            self._recovery_probe_task.cancel()
