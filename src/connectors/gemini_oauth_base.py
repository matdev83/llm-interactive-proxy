"""
Base class for Gemini OAuth connectors.
"""

import abc
import asyncio
import contextlib
import hashlib
import json
import logging
import random
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import AsyncGenerator, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import google.auth
import google.auth.transport.requests
import google.oauth2.credentials
import httpx
import requests  # type: ignore[import-untyped]
import tiktoken
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
)

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

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

from .gemini import GeminiBackend
from .mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin

# Code Assist API endpoint (matching the CLI's endpoint):
#   https://cloudcode-pa.googleapis.com
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
# API version: v1internal
# Default model example: "codechat-bison"
# Default project for free tier used in UserTierId enum: "free-tier"

logger = logging.getLogger(__name__)


TOKEN_EXPIRY_BUFFER_SECONDS = 30.0
CLI_REFRESH_THRESHOLD_SECONDS = 120.0
CLI_REFRESH_COOLDOWN_SECONDS = 30.0
TOKEN_REFRESH_MAX_WAIT_SECONDS = 30.0
TOKEN_REFRESH_POLL_INTERVAL_SECONDS = 1.0
CLI_REFRESH_COMMAND = [
    "gemini",
    "-m",
    "gemini-2.5-flash",
    "-y",
    "-p",
    "Hi. What's up?",
]

# Timeout configuration for streaming requests
# Connection timeout: time to establish connection
DEFAULT_CONNECTION_TIMEOUT = 60.0
# Read timeout: time between chunks during streaming (much longer for large responses)
DEFAULT_READ_TIMEOUT = 300.0  # 5 minutes to handle large file reads and long responses

# Graceful degradation configuration
DEFAULT_RETRY_DELAYS = [15, 30, 60]  # Wait 15s, then 30s, then 60s between retries
DEFAULT_MAX_TOTAL_ATTEMPTS = 9  # Maximum total attempts across all models
DEFAULT_COOLDOWN_DURATION = 600.0  # 10 minutes cooldown after exhaustion
DEFAULT_RECOVERY_PROBE_INTERVAL = 120.0  # Check recovery every 2 minutes

# Code Assist plan-specific prompt allowance (per request).
# The margin stops us before the backend enforces the hard cap.
DEFAULT_CODE_ASSIST_PROMPT_LIMIT = 65_536
CODE_ASSIST_PROMPT_LIMIT_MARGIN = 0.97


@dataclass
class GracefulDegradationConfig:
    """Configuration for graceful degradation behavior."""

    enabled: bool = True
    retry_delays: list[float] = field(
        default_factory=lambda: list(DEFAULT_RETRY_DELAYS)
    )
    max_total_attempts: int = DEFAULT_MAX_TOTAL_ATTEMPTS
    cooldown_duration: float = DEFAULT_COOLDOWN_DURATION
    enable_recovery_probing: bool = True
    recovery_probe_interval: float = DEFAULT_RECOVERY_PROBE_INTERVAL

    @classmethod
    def from_config(cls, config: AppConfig) -> "GracefulDegradationConfig":
        """Create configuration from AppConfig."""

        # AppConfig exposes attributes rather than dict-like `.get()` in some contexts
        def _coerce_list(value: Any, default: Sequence[float]) -> list[float]:
            if isinstance(value, list | tuple):
                return [float(v) for v in value]
            if value is None:
                return list(default)
            try:
                return [float(v) for v in list(value)]
            except Exception:
                return list(default)

        return cls(
            enabled=bool(getattr(config, "graceful_degradation_enabled", True)),
            retry_delays=_coerce_list(
                getattr(
                    config,
                    "graceful_degradation_retry_delays",
                    DEFAULT_RETRY_DELAYS,
                ),
                DEFAULT_RETRY_DELAYS,
            ),
            max_total_attempts=int(
                getattr(
                    config,
                    "graceful_degradation_max_attempts",
                    DEFAULT_MAX_TOTAL_ATTEMPTS,
                )
            ),
            cooldown_duration=float(
                getattr(
                    config,
                    "graceful_degradation_cooldown",
                    DEFAULT_COOLDOWN_DURATION,
                )
            ),
            enable_recovery_probing=bool(
                getattr(
                    config,
                    "graceful_degradation_recovery_probing",
                    True,
                )
            ),
            recovery_probe_interval=float(
                getattr(
                    config,
                    "graceful_degradation_probe_interval",
                    DEFAULT_RECOVERY_PROBE_INTERVAL,
                )
            ),
        )


@dataclass
class GracefulDegradationMetrics:
    """Lightweight telemetry for graceful degradation behavior."""

    total_invocations: int = 0
    total_attempts: int = 0
    fallback_invocations: int = 0
    total_wait_time: float = 0.0
    last_duration: float = 0.0

    def record_attempt(self) -> None:
        self.total_attempts += 1

    def record_wait(self, wait_seconds: float) -> None:
        if wait_seconds > 0:
            self.total_wait_time += wait_seconds

    def record_fallback(self) -> None:
        self.fallback_invocations += 1

    def record_duration(self, duration_seconds: float) -> None:
        self.last_duration = max(0.0, duration_seconds)

    def as_dict(self) -> dict[str, float | int]:
        return {
            "total_invocations": self.total_invocations,
            "total_attempts": self.total_attempts,
            "fallback_invocations": self.fallback_invocations,
            "total_wait_time": self.total_wait_time,
            "last_duration": self.last_duration,
        }


@dataclass
class ModelRetryState:
    """State tracking for model retry attempts."""

    attempts: int = 0
    cooldown_until: float = 0.0
    last_probe_attempt: float = 0.0
    probe_success_count: int = 0


class GeminiPersonalCredentialsFileHandler(FileSystemEventHandler):
    """File system event handler for monitoring OAuth credentials file changes."""

    def __init__(self, connector: "GeminiOAuthBaseConnector"):
        """Initialize the file handler with reference to the connector.

        Args:
            connector: The GeminiOAuthPersonalConnector instance to notify of file changes
        """
        super().__init__()
        self.connector = connector

    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and isinstance(event.src_path, str):
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                credentials_path = (
                    self.connector._credentials_path.resolve()
                    if self.connector._credentials_path
                    else None
                )

                if credentials_path and event_path == credentials_path:
                    try:
                        current_mtime = event_path.stat().st_mtime
                    except OSError:
                        current_mtime = None

                    last_mtime = self.connector._last_credentials_event_mtime
                    if (
                        current_mtime is not None
                        and last_mtime is not None
                        and current_mtime == last_mtime
                    ):
                        return

                    self.connector._last_credentials_event_mtime = current_mtime
                    file_hash: str | None = None
                    try:
                        file_hash = hashlib.sha256(event_path.read_bytes()).hexdigest()
                    except OSError:
                        file_hash = None

                    if file_hash is not None:
                        if (
                            file_hash == self.connector._credentials_file_hash
                            or file_hash == self.connector._last_credentials_event_hash
                        ):
                            logger.debug(
                                "Credentials file event ignored (unchanged hash): %s",
                                event.src_path,
                            )
                            return
                        self.connector._last_credentials_event_hash = file_hash

                    now = time.time()
                    if now - self.connector._last_credentials_event_log_ts >= 30:
                        logger.info("Credentials file modified: %s", event.src_path)
                        self.connector._last_credentials_event_log_ts = now
                    else:
                        logger.debug(
                            "Credentials file modified (suppressed log window): %s",
                            event.src_path,
                        )

                    # Schedule credential reload in the connector's event loop in a thread-safe way
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                logger.error(f"Error processing file modification event: {e}")


class _StaticTokenCreds:
    """Simple credentials wrapper for static OAuth tokens."""

    def __init__(self, token: str) -> None:
        self.token = token

    def before_request(
        self, request: Any, method: str, url: str, headers: dict
    ) -> None:
        """Apply the token to the authentication header."""
        headers["Authorization"] = f"Bearer {self.token}"

    def refresh(self, request: Any) -> None:
        """No-op: token is managed by the CLI; we reload from file when needed."""
        return


class GeminiOAuthBaseConnector(GeminiBackend, GeminiCodeAssistMixin, abc.ABC):
    """Base class for Gemini OAuth connectors."""

    default_prompt_limit: int | None = DEFAULT_CODE_ASSIST_PROMPT_LIMIT
    prompt_limit_overrides: dict[str, int] = {}
    prompt_limit_prefix_overrides: tuple[tuple[str, int], ...] = ()

    _project_id: str | None = None

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
        self, credentials: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate the structure and content of OAuth credentials.

        Args:
            credentials: The credentials dictionary to validate

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
                if current_utc_s >= float(expiry) / 1000.0 and logger.isEnabledFor(
                    logging.INFO
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

            if is_quota_error:
                self._mark_backend_unusable()
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

    def _mark_backend_unusable(self) -> None:
        """Mark this backend as unusable by removing it from functional backends list.

        This method is called when quota exceeded errors are detected and the backend
        should no longer be used for requests.
        """
        # We don't have direct access to the DI container here; just mark ourselves unusable.
        self.is_functional = False
        self._quota_exceeded = True

        logger.error(
            "Backend %s marked as unusable due to quota exceeded. "
            "Manual intervention may be required to restore functionality.",
            self.name,
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
            logger.info(f"Started watching credentials file: {self._credentials_path}")
        except Exception as e:
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
            logger.info("Handling credentials file change...")

            previous_fingerprint = self._credentials_fingerprint

            # Validate file first
            ok, errs = self._validate_credentials_file_exists()
            if not ok:
                self._degrade(errs)
                logger.warning(
                    f"Updated credentials file is invalid: {'; '.join(errs)}"
                )
                return

            # Attempt to reload with force_reload=True to bypass cache
            if await self._load_oauth_credentials(force_reload=True):
                if (
                    previous_fingerprint is not None
                    and previous_fingerprint == self._credentials_fingerprint
                ):
                    logger.debug(
                        "Credentials file change detected but contents are unchanged; skipping reload."
                    )
                    success = True
                    return
                refreshed = await self._refresh_token_if_needed()
                if refreshed:
                    self._recover()
                    logger.info("Successfully reloaded credentials from updated file")
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
        if not self._oauth_credentials:
            return None

        expiry_value = self._oauth_credentials.get("expiry_date")
        if not isinstance(expiry_value, int | float):
            return None

        expiry_seconds = float(expiry_value) / 1000.0
        return expiry_seconds - time.time()

    def _is_token_expired(
        self, buffer_seconds: float = TOKEN_EXPIRY_BUFFER_SECONDS
    ) -> bool:
        """Check if the current access token is expired or within buffer window."""
        if not self._oauth_credentials:
            return True

        seconds_remaining = self._seconds_until_token_expiry()
        if seconds_remaining is None:
            return False

        return seconds_remaining <= buffer_seconds

    def _should_trigger_cli_refresh(self) -> bool:
        """Determine whether we should proactively trigger CLI token refresh."""
        if not self._oauth_credentials:
            return True

        seconds_remaining = self._seconds_until_token_expiry()
        if seconds_remaining is None:
            return False

        if seconds_remaining > CLI_REFRESH_THRESHOLD_SECONDS:
            return False

        now = time.time()
        if (now - self._last_cli_refresh_attempt) < CLI_REFRESH_COOLDOWN_SECONDS:
            return False

        return not (
            self._cli_refresh_process and self._cli_refresh_process.poll() is None
        )

    def _launch_cli_refresh_process(self) -> None:
        """Launch gemini CLI command to refresh the OAuth token in background."""
        now = time.time()

        if (now - self._last_cli_refresh_attempt) < CLI_REFRESH_COOLDOWN_SECONDS:
            return

        if self._cli_refresh_process and self._cli_refresh_process.poll() is None:
            return

        try:
            command = list(CLI_REFRESH_COMMAND)
            executable = shutil.which(command[0])
            if executable:
                command[0] = executable
            else:
                raise FileNotFoundError(command[0])

            self._cli_refresh_process = subprocess.Popen(  # - intended CLI call
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._last_cli_refresh_attempt = now
            logger.info("Triggered Gemini CLI background refresh process")
        except FileNotFoundError:
            self._last_cli_refresh_attempt = now
            logger.error(
                "Gemini CLI binary not found; cannot refresh OAuth token automatically."
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            self._last_cli_refresh_attempt = now
            logger.error(
                "Failed to launch Gemini CLI for token refresh: %s",
                exc,
                exc_info=True,
            )

    async def _poll_for_new_token(self, max_wait_seconds: float | None = None) -> bool:
        """Poll the credential file for an updated token after CLI refresh."""
        if not self._is_token_expired():
            return True

        wait_window = (
            TOKEN_REFRESH_MAX_WAIT_SECONDS
            if max_wait_seconds is None
            else max_wait_seconds
        )
        if wait_window <= 0:
            return not self._is_token_expired()

        deadline = time.time() + wait_window
        attempts = 0

        while time.time() < deadline:
            remaining = deadline - time.time()
            sleep_for = min(TOKEN_REFRESH_POLL_INTERVAL_SECONDS, remaining)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            attempts += 1
            loaded = await self._load_oauth_credentials()
            if loaded and not self._is_token_expired():
                logger.debug("Token refresh succeeded after %d poll attempts", attempts)
                return True

        # One final check in case the token refreshed just as the loop exited
        loaded = await self._load_oauth_credentials()
        if loaded and not self._is_token_expired():
            logger.debug(
                "Token refresh finalized after max wait window (%s seconds)",
                wait_window,
            )
            return True

        return not self._is_token_expired()

    def _get_refresh_token(self) -> str | None:
        """Get refresh token, either from credentials or cached value."""
        if self._refresh_token:
            return self._refresh_token

        if self._oauth_credentials and "refresh_token" in self._oauth_credentials:
            self._refresh_token = self._oauth_credentials["refresh_token"]
            return self._refresh_token

        return None

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

            logger.warning(
                "Automatic Gemini CLI refresh did not produce a valid token in time."
            )
            return False

    async def _save_oauth_credentials(self, credentials: dict[str, Any]) -> None:
        """Save OAuth credentials to oauth_creds.json file."""
        try:
            home_dir = Path.home()
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
            creds_path = gemini_dir / "oauth_creds.json"

            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(credentials, f, indent=4)
            logger.info(f"Gemini OAuth credentials saved to {creds_path}")
        except OSError as e:
            logger.error(f"Error saving Gemini OAuth credentials: {e}", exc_info=True)

    @staticmethod
    def _compute_credentials_fingerprint(credentials: dict[str, Any]) -> str:
        """Return a stable fingerprint for the currently loaded credentials."""
        relevant = {
            "access_token": credentials.get("access_token", ""),
            "refresh_token": credentials.get("refresh_token", ""),
            "expiry_date": credentials.get("expiry_date"),
        }
        payload = json.dumps(relevant, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8", "ignore")).hexdigest()

    async def _load_oauth_credentials(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from oauth_creds.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

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
                logger.warning(f"Gemini OAuth credentials not found at {creds_path}")
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
            if logger.isEnabledFor(logging.INFO):
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
            logger.error(f"Error loading Gemini OAuth credentials: {e}", exc_info=True)
            return False

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

        Note: The Code Assist API doesn't have a models list endpoint,
        so we use a hardcoded list of known models based on the official
        gemini-cli source code (as of 2025).
        """
        if not self.available_models and self._oauth_credentials:
            # Code Assist API doesn't have a /v1internal/models endpoint
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
            logger.info(f"Loaded {len(self.available_models)} known Code Assist models")

    async def list_models(
        self, *, gemini_api_base_url: str, key_name: str, api_key: str
    ) -> dict[str, Any]:
        """List available models using OAuth authentication - ignores API key params."""
        if not self._oauth_credentials or not self._oauth_credentials.get(
            "access_token"
        ):
            raise HTTPException(
                status_code=401, detail="No OAuth access token available"
            )

        headers = {"Authorization": f"Bearer {self._oauth_credentials['access_token']}"}
        base_url = self.gemini_api_base_url or CODE_ASSIST_ENDPOINT
        url = f"{base_url}/v1internal/models"

        try:
            response = await self.client.get(url, headers=headers)
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
            result: dict[str, Any] = response.json()
            return result
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

            base_url = self.gemini_api_base_url or CODE_ASSIST_ENDPOINT
            headers = {
                "Authorization": f"Bearer {self._oauth_credentials['access_token']}",
                "Content-Type": "application/json",
            }

            # First try the legacy models endpoint (keeps existing tests/assertions working)
            models_url = f"{base_url}/v1internal/models"
            try:
                response = await self.client.get(
                    models_url, headers=headers, timeout=10.0
                )
            except httpx.TimeoutException as te:
                logger.error(
                    f"Health check timeout calling {models_url}: {te}", exc_info=True
                )
                return False
            except httpx.RequestError as rexc:
                logger.error(
                    f"Health check connection error calling {models_url}: {rexc}",
                    exc_info=True,
                )
                return False

            if response.status_code == 200:
                logger.info("Health check passed - API connectivity verified")
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
                            **kwargs,
                        )
                    else:
                        # Graceful degradation disabled, use original behavior
                        self._mark_backend_unusable()
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
            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )
            auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)
            auth_session.headers.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)

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

            prompt_tokens_estimate = self._estimate_prompt_tokens(code_assist_request)
            self._enforce_prompt_limit(
                prompt_tokens_estimate,
                effective_model,
                request_id=getattr(request_data, "id", None),
            )

            # Prepare request body for Code Assist API
            request_body = {
                "model": effective_model,
                "project": project_id,
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

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
            encoding = tiktoken.get_encoding("cl100k_base")
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

            auth_session = google.auth.transport.requests.AuthorizedSession(
                _StaticTokenCreds(access_token)
            )

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

            prompt_tokens_estimate = self._estimate_prompt_tokens(code_assist_request)
            self._enforce_prompt_limit(
                prompt_tokens_estimate,
                effective_model,
                request_id=getattr(request_data, "id", None),
            )

            # Prepare request body for Code Assist API
            request_body = {
                "model": effective_model,
                "project": project_id,
                "user_prompt_id": self._generate_user_prompt_id(request_data),
                "request": code_assist_request,
            }

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
            encoding = tiktoken.get_encoding("cl100k_base")
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

            async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
                import json

                import google.auth.exceptions

                response = None
                generated_text = ""
                error_json_buffer: str | None = None
                done_reasons_to_skip = {"stop", "length", "cancelled"}

                def _should_skip_chunk(chunk: dict[str, Any]) -> bool:
                    """Filter out empty deltas so clients don't receive blank messages."""
                    if not chunk:
                        return True
                    choices = chunk.get("choices") or []
                    if not choices:
                        return True
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
                    if finish_reason in {"error", "tool_calls"}:
                        return False
                    if finish_reason in done_reasons_to_skip:
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
                    except google.auth.exceptions.GoogleAuthError as gae:
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
                        logger.warning(
                            f"Gemini streaming error response: {response.status_code}"
                        )
                        # Handle 429 with graceful degradation
                        if response.status_code == 429:
                            if self._degradation_config.enabled:
                                try:
                                    fallback_response = await self._handle_429_with_graceful_degradation(
                                        original_model=effective_model,
                                        request_data=request_data,
                                        processed_messages=processed_messages,
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
                            # Mark backend unusable for quota-style errors
                            if error_type == "quota_exceeded":
                                self._mark_backend_unusable()
                            return

                        # For non-429 errors, yield error chunk
                        # Graceful error handling - yield error chunk instead of raising exception
                        try:
                            error_detail = response.json()
                        except Exception:
                            error_detail = response.text

                        error_message = ""
                        if isinstance(error_detail, dict):
                            error_message = error_detail.get("error", {}).get(
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
                            self._mark_backend_unusable()
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
                            yield ProcessedResponse(content=error_chunk)
                            return
                        else:
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
                            yield ProcessedResponse(content=error_chunk)
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
                                domain_chunk = (
                                    self.translation_service.to_domain_stream_chunk(
                                        chunk=data, source_format="code_assist"
                                    )
                                )
                                if domain_chunk is not None:
                                    domain_chunk["model"] = effective_model
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
                                model="gemini-oauth",
                                usage=None,
                                key_name=getattr(self, "_key_name", None),
                            ).model_dump()

                            metadata.update(
                                {
                                    "raw_tool_calls": domain_chunk.get("choices", [{}])[
                                        0
                                    ]
                                    .get("delta", {})
                                    .get("tool_calls"),
                                    "raw_finish_reason": domain_chunk.get(
                                        "choices", [{}]
                                    )[0].get("finish_reason"),
                                }
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

                            for processed_chunk in _process_decoded_line(decoded_line):
                                yield processed_chunk
                            if done:
                                break

                    if not done and line_buffer:
                        for processed_chunk in _process_decoded_line(
                            line_buffer.rstrip("\r\n")
                        ):
                            yield processed_chunk
                        line_buffer = ""

                    logger.debug(
                        f"[STREAMING] Calculating usage for generated_text length={len(generated_text)}, prompt_tokens={prompt_tokens}"
                    )
                    try:
                        completion_tokens = len(encoding.encode(generated_text))
                        usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": (prompt_tokens or 0) + completion_tokens,
                        }
                        usage_chunk = {
                            "id": f"chatcmpl-gemini-usage-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": effective_model,
                            "choices": [],
                            "usage": usage,
                        }
                        logger.debug(f"[STREAMING] Yielding usage chunk: {usage_chunk}")
                        yield ProcessedResponse(content=usage_chunk)
                    except Exception as e:
                        logger.warning(
                            f"Could not calculate completion tokens for streaming: {e}"
                        )

                    final_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk=None, source_format="code_assist"
                    )
                    yield ProcessedResponse(content=final_chunk)

                except BackendError as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    raise
                except Exception as e:
                    logger.error(f"Error in streaming generator: {e}", exc_info=True)
                    error_chunk = self.translation_service.to_domain_stream_chunk(
                        chunk=None, source_format="code_assist"
                    )
                    yield ProcessedResponse(content=error_chunk)
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
        """Build Code Assist generationConfig from request_data using Pydantic models."""
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

    def _get_fallback_model(self, original_model: str) -> str | None:
        """Get the fallback model for a given model.

        Args:
            original_model: The model that needs fallback

        Returns:
            The fallback model name, or None if no fallback available
        """
        fallback_map = {
            "gemini-2.5-pro": "gemini-2.5-flash",
            "gemini-2.5-flash": None,  # No fallback for flash
            "gemini-2.5-flash-lite": None,
            "gemini-2.5-pro-preview-05-06": "gemini-2.5-flash",
            "gemini-2.5-pro-preview-06-05": "gemini-2.5-flash",
            "gemini-2.5-flash-preview-05-20": None,
            "gemini-2.0-flash": "gemini-1.5-flash",
            "gemini-1.5-pro": "gemini-1.5-flash",
            "gemini-1.5-flash": None,
        }
        return fallback_map.get(original_model)

    def _is_in_cooldown(self, model: str) -> bool:
        """Check if a model is currently in cooldown.

        Args:
            model: The model to check

        Returns:
            True if model is in cooldown, False otherwise
        """
        state = self._model_retry_states.get(model)
        if not state:
            return False
        return time.time() < state.cooldown_until

    def _set_cooldown(self, model: str) -> None:
        """Put a model into cooldown state.

        Args:
            model: The model to put in cooldown
        """
        if model not in self._model_retry_states:
            self._model_retry_states[model] = ModelRetryState()

        state = self._model_retry_states[model]
        state.cooldown_until = time.time() + self._degradation_config.cooldown_duration
        state.attempts = 0  # Reset attempts after cooldown
        state.probe_success_count = 0

        logger.info(f"Model {model} put in cooldown until {state.cooldown_until}")

    @staticmethod
    def _is_rate_limit_like_error(error: BackendError) -> bool:
        """Determine whether an error should trigger graceful degradation retries."""

        code = getattr(error, "code", None)
        status = getattr(error, "status_code", None)
        return status == 429 or (isinstance(code, str) and code in {"empty_response"})

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
            self._mark_backend_unusable()
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
            models_to_try.append(fallback_model)

        start_time = time.time()
        self._graceful_metrics.total_invocations += 1

        for _, model in enumerate(models_to_try):
            # Reset attempts for this model if needed
            if model not in self._model_retry_states:
                self._model_retry_states[model] = ModelRetryState()

            state = self._model_retry_states[model]

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
            is_fallback_model = fallback_model is not None and model == fallback_model
            fallback_recorded = False
            max_attempts_for_model = len(self._degradation_config.retry_delays) + 1
            if model == original_model and fallback_model:
                max_attempts_for_model = 1

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
                    if attempt == 0:
                        # First attempt, no delay
                        pass
                    else:
                        # Retry with delay and jitter to prevent thundering herd
                        delay_idx = min(
                            attempt - 1, len(self._degradation_config.retry_delays) - 1
                        )
                        base_delay = self._degradation_config.retry_delays[delay_idx]

                        # Add jitter: ±25% of the base delay to prevent synchronized retries
                        jitter_factor = 0.25
                        jitter_range = base_delay * jitter_factor
                        jitter = random.uniform(-jitter_range, jitter_range)
                        delay = max(0, base_delay + jitter)  # Ensure non-negative delay

                        logger.info(
                            f"Retrying model {model} after {delay:.1f}s delay (attempt {attempt}, base: {base_delay}s, jitter: {jitter:+.1f}s)"
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
                self._set_cooldown(model)

                # Start recovery probing task if enabled
                if self._degradation_config.enable_recovery_probing and (
                    self._recovery_probe_task is None
                    or self._recovery_probe_task.done()
                ):
                    self._recovery_probe_task = asyncio.create_task(
                        self._recovery_probing_loop()
                    )
            elif model == fallback_model:
                # Fallback model failed, mark backend as unusable
                if fallback_model == "gemini-2.5-flash" or not fallback_model:
                    # Flash model failed or no fallback, mark backend unusable
                    self._mark_backend_unusable()
                    self._permanently_failed = True
                    self.is_functional = False

        # If we get here, all models failed
        self._graceful_metrics.record_duration(time.time() - start_time)
        self._mark_backend_unusable()
        self._permanently_failed = True
        raise BackendError(
            message="All models exhausted in graceful degradation",
            code="all_models_exhausted",
            status_code=429,
        )

    async def _recovery_probing_loop(self) -> None:
        """Background task to probe for model recovery."""
        if not self._degradation_config.enable_recovery_probing:
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
        if self._cli_refresh_process and self._cli_refresh_process.poll() is None:
            with contextlib.suppress(Exception):
                self._cli_refresh_process.terminate()
        self._cli_refresh_process = None

        # Cancel recovery probe task if running
        # During shutdown, we need to cancel the task without trying to schedule it
        # on the event loop, which may already be closed
        if self._recovery_probe_task and not self._recovery_probe_task.done():
            # Simply cancel without awaiting - the task will be cleaned up
            # We suppress all exceptions because during interpreter shutdown,
            # the logging system may already be torn down
            with contextlib.suppress(Exception):
                self._recovery_probe_task.cancel()
        self._recovery_probe_task = None
