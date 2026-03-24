from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import INotificationService
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.chat_history_utils import stringify_tool_calls_and_results
from src.core.domain.model_utils import (
    ParsedModelWithParams,
    parse_model_backend,
    parse_model_with_params,
)
from src.core.domain.quality_verifier import QualityVerifierDecision
from src.core.domain.quality_verifier_turns import QV_ELIGIBLE_TURN_SCALE
from src.core.services.quality_verifier_prompt_loader import (
    QualityVerifierPromptLoader,
)

logger = logging.getLogger(__name__)

VerifierTextCallFn = Callable[[ChatRequest], Awaitable[str | None]]

# Global prompt loader instance with thread-safe initialization
_prompt_loader: QualityVerifierPromptLoader | None = None
_prompt_loader_lock = threading.Lock()


@dataclass
class _ModelHealth:
    consecutive_failures: int = 0
    unhealthy_until: datetime | None = None


# Health state for Quality Verifier models (model_spec -> _ModelHealth)
_model_health: dict[str, _ModelHealth] = {}
_health_lock = threading.Lock()


def get_quality_verifier_prompt_loader() -> QualityVerifierPromptLoader:
    """Get or initialize the global prompt loader instance.

    Uses double-checked locking for thread-safe singleton initialization.
    """
    global _prompt_loader
    if _prompt_loader is None:
        with _prompt_loader_lock:
            # Double-check after acquiring lock
            if _prompt_loader is None:
                loader = QualityVerifierPromptLoader()
                loader.load_prompts()
                _prompt_loader = loader
    return _prompt_loader


class QualityVerifierService:
    """Service orchestrating Quality Verifier and steering."""

    _NO_STEERING_RE = re.compile(
        r"<status>\s*NO_STEERING_NEEDED\s*</status>",
        re.IGNORECASE,
    )
    _STEERING_RE = re.compile(
        r"<steering>([\s\S]*?)</steering>",
        re.IGNORECASE,
    )
    _TOOL_DEFINITION_TAG_RE = re.compile(
        r"<(?:tools|tool_definitions)>[\s\S]*?</(?:tools|tool_definitions)>",
        re.IGNORECASE,
    )
    _FENCED_BLOCK_RE = re.compile(r"```(?:json|yaml)?\s*([\s\S]*?)```", re.IGNORECASE)
    _MAX_INVALID_OUTPUT_CHARS = 4000

    def __init__(
        self,
        model_spec: str | None,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service: INotificationService | None = None,
    ) -> None:
        self._model_spec = (model_spec or "").strip()
        self._max_history = max_history
        self._max_consecutive_failures = max_consecutive_failures
        self._cooldown_seconds = cooldown_seconds
        self._notification_service = notification_service

    def is_enabled(self) -> bool:
        return bool(self._model_spec and self._model_spec.strip())

    def is_healthy(self) -> bool:
        """Check if the Quality Verifier model is currently healthy (circuit breaker)."""
        if not self.is_enabled():
            return False

        with _health_lock:
            health = _model_health.get(self._model_spec)
            if health is None:
                return True

            if health.unhealthy_until is None:
                return True

            if datetime.now() > health.unhealthy_until:
                # Cool-down expired, allow one probe
                logger.info(
                    "Quality Verifier model %s cool-down expired; allowing probe request",
                    self._model_spec,
                )
                return True

            return False

    async def report_success(self) -> None:
        """Report a successful call to the Quality Verifier model to reset health state."""
        if not self.is_enabled():
            return

        with _health_lock:
            if self._model_spec in _model_health:
                logger.debug(
                    "Resetting health state for Quality Verifier model %s",
                    self._model_spec,
                )
                del _model_health[self._model_spec]

    async def report_failure(self) -> None:
        """Report a failed call to the Quality Verifier model to update health state."""
        if not self.is_enabled():
            return

        with _health_lock:
            health = _model_health.get(self._model_spec)
            if health is None:
                health = _ModelHealth()
                _model_health[self._model_spec] = health

            health.consecutive_failures += 1
            if health.consecutive_failures >= self._max_consecutive_failures:
                unhealthy_until = datetime.now() + timedelta(
                    seconds=self._cooldown_seconds
                )
                health.unhealthy_until = unhealthy_until

                logger.warning(
                    "Quality Verifier model %s reached %d consecutive failures; "
                    "tripping circuit breaker until %s",
                    self._model_spec,
                    health.consecutive_failures,
                    unhealthy_until.isoformat(),
                )

                # Send desktop notification if service is available
                if self._notification_service:
                    try:
                        title = "Quality Verifier Disabled"
                        message = (
                            f"Model '{self._model_spec}' reached {health.consecutive_failures} "
                            f"consecutive failures. Quality Verifier is disabled until {unhealthy_until.strftime('%H:%M:%S')}."
                        )
                        # Fire and forget notification, but keep a reference to avoid
                        # unobserved task warnings and satisfy linting expectations.
                        import asyncio

                        notification_task = asyncio.create_task(
                            self._notification_service.send_notification(title, message)
                        )

                        def _consume_notification_result(task: asyncio.Task) -> None:
                            try:
                                task.result()
                            except Exception:
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Quality Verifier notification task failed",
                                        exc_info=True,
                                    )

                        notification_task.add_done_callback(
                            _consume_notification_result
                        )
                    except Exception as e:
                        logger.debug(
                            "Failed to send Quality Verifier failure notification: %s",
                            e,
                        )
            else:
                logger.debug(
                    "Quality Verifier model %s failure recorded (%d/%d)",
                    self._model_spec,
                    health.consecutive_failures,
                    self._max_consecutive_failures,
                )

    @staticmethod
    def should_run_for_request(request: ChatRequest, frequency: int | None) -> bool:
        try:
            freq = int(frequency) if frequency is not None else 10
        except (TypeError, ValueError):
            freq = 10
        if freq <= 1:
            freq = 1
        user_turns = sum(1 for message in request.messages if message.role == "user")
        if user_turns <= 0:
            return False
        return user_turns % freq == 0

    @staticmethod
    def coerce_eligible_turn_floor(raw: Any) -> int | None:
        """Convert stored eligible-turn counters to a scheduling floor.

        Values may be **scaled integers** (``logical * QV_ELIGIBLE_TURN_SCALE``),
        legacy fractional floats (e.g. ``8.2`` logical), or small legacy ints
        (whole logical turns).

        Returns None when the value is missing or unusable so callers can fall back
        to :meth:`should_run_for_request`.
        """
        if raw is None or isinstance(raw, dict | list):
            return None
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int) and not isinstance(raw, bool):
            if raw <= 0:
                return None
            if raw >= QV_ELIGIBLE_TURN_SCALE:
                return raw // QV_ELIGIBLE_TURN_SCALE
            return int(raw)
        try:
            if isinstance(raw, str):
                stripped = raw.strip()
                if not stripped:
                    return None
                value = float(stripped)
            else:
                value = float(raw)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        if value >= float(QV_ELIGIBLE_TURN_SCALE) and abs(value - int(value)) < 1e-9:
            return int(value) // QV_ELIGIBLE_TURN_SCALE
        return int(value)

    @staticmethod
    def should_run_verification(
        request: ChatRequest,
        frequency: int | None,
        *,
        eligible_turn_raw: Any = None,
    ) -> bool:
        """Whether Quality Verifier should run for this completion (scheduling only).

        Prefer ``eligible_turn_raw`` from :attr:`RequestContext.extensions` (set by the
        request processor). When it is missing, falls back to counting ``user`` messages
        in ``request`` (legacy / tests).
        """
        try:
            freq_int = int(frequency) if frequency is not None else 10
        except (TypeError, ValueError):
            freq_int = 10
        if freq_int <= 0:
            freq_int = 1

        floor = QualityVerifierService.coerce_eligible_turn_floor(eligible_turn_raw)
        if floor is not None:
            return floor > 0 and (floor % freq_int == 0)
        return QualityVerifierService.should_run_for_request(request, frequency)

    async def maybe_retry_verifier_for_valid_xml(
        self,
        verification_request: ChatRequest,
        first_text: str | None,
        call_verifier: VerifierTextCallFn,
    ) -> str | None:
        """If the first verifier output is malformed, run one format-correction round trip."""
        if first_text is None:
            return None
        ok, reason = self.validate_quality_verifier_output_format(first_text)
        if ok:
            return first_text
        retry_req = self.build_invalid_format_retry_request(
            verification_request, first_text, reason
        )
        return await call_verifier(retry_req)

    @staticmethod
    def is_tool_result_followup_request(request: ChatRequest) -> bool:
        """Return True when the request is a tool-result continuation.

        Tool-result continuation requests typically contain one or more `tool` role
        messages after the most recent `user` message. Verifying the *completion*
        for such requests can lead to surprising behavior because the request payload
        is largely produced by the tool execution environment rather than the user.

        This is intentionally conservative: it only flags a request as a tool-followup
        when the most recent tool message appears after the most recent user message.
        """

        try:
            last_user_idx = -1
            last_tool_idx = -1

            for idx, msg in enumerate(getattr(request, "messages", []) or []):
                role = getattr(msg, "role", None)
                # Some call sites may provide dict-like messages.
                if role is None and isinstance(msg, dict):
                    role = msg.get("role")

                if role == "user":
                    last_user_idx = idx
                elif role == "tool":
                    last_tool_idx = idx

            return last_tool_idx > last_user_idx and last_user_idx >= 0
        except Exception:
            # Fail-open: if we cannot reliably detect, do not classify as tool-followup.
            return False

    def parse_model(self, default_backend: str = "") -> ParsedModelWithParams:
        return parse_model_with_params(self._model_spec, default_backend)

    @staticmethod
    def _compose_model_identifier(backend: str, model: str) -> str:
        return f"{backend}:{model}" if backend else model

    @staticmethod
    def _normalize_assistant_content(assistant_response: Any) -> str:
        if assistant_response is None:
            return ""
        if isinstance(assistant_response, str):
            return assistant_response
        return str(assistant_response)

    def _resolve_model_for_request(
        self, original_request: ChatRequest | None
    ) -> ParsedModelWithParams:
        default_backend = ""
        if original_request is not None:
            try:
                parsed = parse_model_backend(original_request.model)
                default_backend = parsed.backend_type
            except (ValueError, TypeError) as exc:
                logger.debug(
                    "Failed to parse model backend for Quality Verifier: %s",
                    exc,
                    exc_info=True,
                )
                default_backend = ""
            except Exception as exc:
                logger.warning(
                    "Unexpected error parsing model backend for Quality Verifier: %s",
                    exc,
                    exc_info=True,
                )
                default_backend = ""
        return self.parse_model(default_backend)

    def build_verification_messages(
        self, request: ChatRequest, assistant_response: Any
    ) -> list[ChatMessage]:
        loader = get_quality_verifier_prompt_loader()
        messages = [ChatMessage(role="system", content=loader.quality_verifier_prompt)]

        # History stringification: convert tool calls/results to text for cross-backend compatibility.
        history = stringify_tool_calls_and_results(list(request.messages))
        history = self._sanitize_history_for_quality_verifier(history)

        # Truncate history for Quality Verifier if enabled
        max_history = self._max_history
        if max_history is not None and max_history > 0 and len(history) > max_history:
            history = history[-max_history:]

        # Include (potentially truncated) context
        messages.extend(history)
        # Attach last assistant response
        normalized = self._normalize_assistant_content(assistant_response)
        messages.append(ChatMessage(role="assistant", content=normalized))
        return messages

    @staticmethod
    def _looks_like_tool_definition_item(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if value.get("type") == "function" and isinstance(value.get("function"), dict):
            return True
        return isinstance(value.get("name"), str) and (
            "parameters" in value or "description" in value
        )

    @classmethod
    def _is_serialized_tool_definitions(cls, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if not stripped.startswith("{") and not stripped.startswith("["):
            return False

        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return False
        except Exception:
            return False

        if isinstance(payload, dict):
            tools = payload.get("tools")
            if (
                isinstance(tools, list)
                and tools
                and all(cls._looks_like_tool_definition_item(item) for item in tools)
            ):
                return True
            return cls._looks_like_tool_definition_item(payload)

        if isinstance(payload, list) and payload:
            return all(cls._looks_like_tool_definition_item(item) for item in payload)

        return False

    @classmethod
    def _strip_tool_definition_wrappers(cls, text: str) -> str:
        cleaned = cls._TOOL_DEFINITION_TAG_RE.sub(
            "[Tool definitions omitted for Quality Verifier audit.]", text
        )

        def _replace_fenced_block(match: re.Match[str]) -> str:
            fenced_content = (match.group(1) or "").strip()
            if cls._is_serialized_tool_definitions(fenced_content):
                return "[Tool definitions omitted for Quality Verifier audit.]"
            lower = fenced_content.lower()
            if '"tools"' in lower and '"function"' in lower:
                return "[Tool definitions omitted for Quality Verifier audit.]"
            return match.group(0)

        return cls._FENCED_BLOCK_RE.sub(_replace_fenced_block, cleaned)

    def _sanitize_history_for_quality_verifier(
        self, history: list[ChatMessage]
    ) -> list[ChatMessage]:
        sanitized: list[ChatMessage] = []
        for message in history:
            if message.role == "system":
                continue

            content = message.content
            if isinstance(content, str):
                content = self._strip_tool_definition_wrappers(content).strip() or None
                if isinstance(content, str) and self._is_serialized_tool_definitions(
                    content
                ):
                    content = "[Tool definitions omitted for Quality Verifier audit.]"

            sanitized.append(
                ChatMessage(
                    role=message.role,
                    content=content,
                    reasoning_content=message.reasoning_content,
                    name=message.name,
                    metadata=message.metadata.copy() if message.metadata else None,
                )
            )

        return sanitized

    def validate_quality_verifier_output_format(
        self, text: str
    ) -> tuple[bool, str | None]:
        no_steering_match = bool(self._NO_STEERING_RE.search(text))
        steering_match = self._STEERING_RE.search(text)

        if no_steering_match and steering_match:
            return False, "Response contains both <status> and <steering> tags."

        if no_steering_match:
            return True, None

        if steering_match:
            if not (steering_match.group(1) or "").strip():
                return False, "<steering> tag is empty."
            return True, None

        return False, "Missing required <status> or <steering> XML tags."

    def build_invalid_format_retry_request(
        self,
        verification_request: ChatRequest,
        invalid_output: str,
        failure_reason: str | None = None,
    ) -> ChatRequest:
        reason = (failure_reason or "Missing or malformed XML tags.").strip()
        invalid_clean = (invalid_output or "").strip()
        if len(invalid_clean) > self._MAX_INVALID_OUTPUT_CHARS:
            invalid_clean = (
                invalid_clean[: self._MAX_INVALID_OUTPUT_CHARS] + "\n... (truncated)"
            )

        correction_instruction = (
            "[SYSTEM MESSAGE: QUALITY VERIFIER FORMAT CORRECTION REQUIRED]\n\n"
            "Your previous Quality Verifier reply did not follow the required XML format.\n"
            f"Detected issue: {reason}\n\n"
            "Previous invalid reply:\n"
            "<invalid_quality_verifier_reply>\n"
            f"{invalid_clean or '(empty response)'}\n"
            "</invalid_quality_verifier_reply>\n\n"
            "Regenerate your output now. It must be EXACTLY one of:\n"
            "1) <status>NO_STEERING_NEEDED</status>\n"
            "2) <steering>...short actionable steering note...</steering>\n"
            "Do not include any extra wrappers or prose outside the required XML tags.\n"
            "Do not call tools or request function calls; reply with plain text only."
        )

        retry_messages = [
            *verification_request.messages,
            ChatMessage(role="assistant", content=invalid_clean or "(empty response)"),
            ChatMessage(role="user", content=correction_instruction),
        ]

        return verification_request.model_copy(
            update={"messages": retry_messages, "stream": True}
        )

    def build_verification_request(
        self, request: ChatRequest, assistant_response: Any
    ) -> ChatRequest:
        messages = self.build_verification_messages(request, assistant_response)
        model_info = self._resolve_model_for_request(request)

        def _to_float(val: Any) -> float | None:
            if val is None or isinstance(val, dict | list):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def _to_int(val: Any) -> int | None:
            if val is None or isinstance(val, dict | list):
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        # Prepare verification request
        return ChatRequest(
            model=self._compose_model_identifier(
                model_info.backend_type, model_info.model_name
            ),
            messages=messages,
            stream=True,
            # Pass through sampling parameters if provided in model spec
            temperature=_to_float(model_info.uri_params.get("temperature")),
            top_p=_to_float(model_info.uri_params.get("top_p")),
            max_tokens=_to_int(model_info.uri_params.get("max_tokens")),
            presence_penalty=_to_float(model_info.uri_params.get("presence_penalty")),
            frequency_penalty=_to_float(model_info.uri_params.get("frequency_penalty")),
            extra_body=dict(model_info.uri_params),
        )

    def build_correction_request(
        self, request: ChatRequest, original_response: Any, steering_text: str
    ) -> ChatRequest:
        """Build a synthetic chat request embedding verifier feedback in-message.

        Production steering uses ``quality_verifier_steering_store`` and the request
        transform pipeline instead of this helper; it remains for tests and optional
        alternate flows.
        """
        normalized_response = self._normalize_assistant_content(original_response)

        # History stringification: convert tool calls/results to text for cross-backend compatibility.
        history = stringify_tool_calls_and_results(list(request.messages))

        # Construct correction messages following Role Alternation (Assistant -> User)
        augmented_messages = [
            *history,
            ChatMessage(role="assistant", content=normalized_response),
            ChatMessage(
                role="user",
                content=f"[SYSTEM MESSAGE: VERIFICATION FEEDBACK]\n\n{steering_text}",
            ),
        ]

        return request.model_copy(
            update={"messages": augmented_messages, "stream": False}
        )

    def build_steering_payload(
        self, request: ChatRequest, original_response: Any, steering_text: str
    ) -> ChatRequest:
        """Alias for :meth:`build_correction_request` (not used by the live proxy path)."""

        return self.build_correction_request(request, original_response, steering_text)

    def parse_quality_verifier_output(self, text: str) -> QualityVerifierDecision:
        """Parse Quality Verifier model output for decisions and steering messages.

        Returns:
            QualityVerifierDecision with 'pass' or 'steer' and optional steering message.
        """
        try:
            if self._NO_STEERING_RE.search(text):
                return QualityVerifierDecision(decision="pass")

            steering_match = self._STEERING_RE.search(text)
            if steering_match:
                msg = (steering_match.group(1) or "").strip()
                if msg:
                    return QualityVerifierDecision(
                        decision="steer",
                        steering_message=msg,
                    )

            # Soft fail-open: ignore malformed / free-form output
            return QualityVerifierDecision(decision="pass")
        except Exception as e:
            # Absolute fail-open: return pass on any parsing error
            logger.warning(
                "Failed to parse Quality Verifier output: %s",
                e,
                exc_info=True,
            )
            return QualityVerifierDecision(decision="pass")
