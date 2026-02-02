from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import INotificationService
from src.core.domain.angel import AngelDecision
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.chat_history_utils import stringify_tool_calls_and_results
from src.core.domain.model_utils import (
    ParsedModelWithParams,
    parse_model_backend,
    parse_model_with_params,
)
from src.core.services.angel_prompt_loader import (
    AngelPromptLoader,
)

logger = logging.getLogger(__name__)

# Global prompt loader instance with thread-safe initialization
_prompt_loader: AngelPromptLoader | None = None
_prompt_loader_lock = threading.Lock()


@dataclass
class _ModelHealth:
    consecutive_failures: int = 0
    unhealthy_until: datetime | None = None


# Health state for Angel models (model_spec -> _ModelHealth)
_model_health: dict[str, _ModelHealth] = {}
_health_lock = threading.Lock()


def get_prompt_loader() -> AngelPromptLoader:
    """Get or initialize the global prompt loader instance.

    Uses double-checked locking for thread-safe singleton initialization.
    """
    global _prompt_loader
    if _prompt_loader is None:
        with _prompt_loader_lock:
            # Double-check after acquiring lock
            if _prompt_loader is None:
                loader = AngelPromptLoader()
                loader.load_prompts()
                _prompt_loader = loader
    return _prompt_loader


class AngelService:
    """Service orchestrating Angel verification and steering."""

    _PASS_DECISION_RE = re.compile(
        r"<angels_decision>\s*Pass\s*</angels_decision>", re.IGNORECASE
    )
    _STEER_DECISION_RE = re.compile(
        r"<angels_decision>\s*Steer\s*</angels_decision>", re.IGNORECASE
    )
    _STEERING_MESSAGE_RE = re.compile(
        r"<angels_steering_message>([\s\S]*?)</angels_steering_message>", re.IGNORECASE
    )

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
        """Check if the Angel model is currently healthy (circuit breaker)."""
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
                    "Angel model %s cool-down expired; allowing probe request",
                    self._model_spec,
                )
                return True

            return False

    async def report_success(self) -> None:
        """Report a successful call to the Angel model to reset health state."""
        if not self.is_enabled():
            return

        with _health_lock:
            if self._model_spec in _model_health:
                logger.debug(
                    "Resetting health state for Angel model %s", self._model_spec
                )
                del _model_health[self._model_spec]

    async def report_failure(self) -> None:
        """Report a failed call to the Angel model to update health state."""
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
                    "Angel model %s reached %d consecutive failures; "
                    "tripping circuit breaker until %s",
                    self._model_spec,
                    health.consecutive_failures,
                    unhealthy_until.isoformat(),
                )

                # Send desktop notification if service is available
                if self._notification_service:
                    try:
                        title = "Angel Verification Disabled"
                        message = (
                            f"Model '{self._model_spec}' reached {health.consecutive_failures} "
                            f"consecutive failures. Angel is disabled until {unhealthy_until.strftime('%H:%M:%S')}."
                        )
                        # Fire and forget notification
                        import asyncio
                        asyncio.create_task(
                            self._notification_service.send_notification(title, message)
                        )
                    except Exception as e:
                        logger.debug("Failed to send Angel failure notification: %s", e)
            else:
                logger.debug(
                    "Angel model %s failure recorded (%d/%d)",
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
                    "Failed to parse model backend for Angel verification: %s",
                    exc,
                    exc_info=True,
                )
                default_backend = ""
            except Exception as exc:
                logger.warning(
                    "Unexpected error parsing model backend for Angel verification: %s",
                    exc,
                    exc_info=True,
                )
                default_backend = ""
        return self.parse_model(default_backend)

    def build_verification_messages(
        self, request: ChatRequest, assistant_response: Any
    ) -> list[ChatMessage]:
        loader = get_prompt_loader()
        messages = [ChatMessage(role="system", content=loader.angel_prompt)]

        # History stringification: convert tool calls/results to text for cross-backend compatibility.
        history = stringify_tool_calls_and_results(list(request.messages))

        # Truncate history for Angel verification if enabled
        max_history = self._max_history
        if max_history is not None and max_history > 0 and len(history) > max_history:
            # Always try to keep the original system prompt if it's the first message
            if history and history[0].role == "system":
                truncated = [history[0]] + history[-(max_history - 1) :]
            else:
                truncated = history[-max_history:]
            history = truncated

        # Include (potentially truncated) context
        messages.extend(history)
        # Attach last assistant response
        normalized = self._normalize_assistant_content(assistant_response)
        messages.append(ChatMessage(role="assistant", content=normalized))
        return messages

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
            stream=False,
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
        """Backward-compatible alias for building a correction request."""

        return self.build_correction_request(request, original_response, steering_text)

    def parse_angel_output(self, text: str) -> AngelDecision:
        """Parse Angel model output for decisions and steering messages.

        Returns:
            AngelDecision with 'pass' or 'steer' and optional steering message.
        """
        try:
            # Explicit Pass check
            if self._PASS_DECISION_RE.search(text):
                return AngelDecision(decision="pass")

            # Explicit Steer check
            steer_match = self._STEER_DECISION_RE.search(text)
            message_match = self._STEERING_MESSAGE_RE.search(text)

            if steer_match or message_match:
                msg = (
                    message_match.group(1).strip()
                    if message_match
                    else "Correction required."
                )
                return AngelDecision(decision="steer", steering_message=msg)

            # Default to pass if output is ambiguous or fails to use tags
            return AngelDecision(decision="pass")
        except Exception as e:
            # Absolute fail-open: return pass on any parsing error
            logger.warning("Failed to parse Angel output: %s", e, exc_info=True)
            return AngelDecision(decision="pass")
