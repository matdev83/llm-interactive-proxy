from __future__ import annotations

import re
import threading
from typing import Any

from src.core.domain.angel import AngelDecision
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_backend, parse_model_with_params
from src.core.services.angel_prompt_loader import (
    AngelPromptLoader,
)

# Global prompt loader instance with thread-safe initialization
_prompt_loader: AngelPromptLoader | None = None
_prompt_loader_lock = threading.Lock()


def get_prompt_loader() -> AngelPromptLoader:
    """Get or initialize the global prompt loader instance.

    Uses double-checked locking for thread-safe singleton initialization.
    """
    global _prompt_loader
    if _prompt_loader is None:
        with _prompt_loader_lock:
            # Double-check after acquiring lock
            if _prompt_loader is None:
                _prompt_loader = AngelPromptLoader()
                _prompt_loader.load_prompts()
    return _prompt_loader


# Backward compatibility: ANGEL_PROMPT constant removed to avoid import-time I/O
# Use get_prompt_loader().angel_prompt instead


class AngelService:
    """Service orchestrating Angel verification and steering."""

    _OVERRIDE_RE = re.compile(
        r"<override_angel>\s*True\s*</override_angel>", re.IGNORECASE
    )

    def __init__(self, model_spec: str | None) -> None:
        self._model_spec = (model_spec or "").strip()

    def is_enabled(self) -> bool:
        return bool(self._model_spec and self._model_spec.strip())

    @staticmethod
    def should_run_for_request(request: ChatRequest, frequency: int | None) -> bool:
        try:
            freq = int(frequency) if frequency is not None else 1
        except (TypeError, ValueError):
            freq = 1
        if freq <= 1:
            freq = 1
        user_turns = sum(1 for message in request.messages if message.role == "user")
        if user_turns <= 0:
            return False
        return user_turns % freq == 0

    def parse_model(self, default_backend: str = "") -> tuple[str, str, dict[str, Any]]:
        backend, model, params = parse_model_with_params(
            self._model_spec, default_backend
        )
        return backend, model, params

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
    ) -> tuple[str, str, dict[str, Any]]:
        default_backend = ""
        if original_request is not None:
            try:
                default_backend, _ = parse_model_backend(original_request.model)
            except Exception:
                default_backend = ""
        return self.parse_model(default_backend)

    def build_verification_messages(
        self, request: ChatRequest, assistant_response: Any
    ) -> list[ChatMessage]:
        loader = get_prompt_loader()
        messages = [ChatMessage(role="system", content=loader.angel_prompt)]
        # Include full context
        messages.extend(list(request.messages))
        # Attach last assistant response
        normalized = self._normalize_assistant_content(assistant_response)
        messages.append(ChatMessage(role="assistant", content=normalized))
        return messages

    def build_verification_request(
        self, request: ChatRequest, assistant_response: Any
    ) -> ChatRequest:
        backend, model, params = self._resolve_model_for_request(request)
        messages = self.build_verification_messages(request, assistant_response)
        target_model = self._compose_model_identifier(backend, model)

        verification = request.model_copy(
            update={
                "model": target_model,
                "messages": messages,
                "stream": False,
            }
        )

        if params:
            verification = verification.model_copy(update={**params})

        return verification

    @staticmethod
    def build_steering_payload(steering_message: str) -> str:
        loader = get_prompt_loader()
        steering_text = loader.steering_template.replace(
            "{angels_steering_message}", steering_message
        )
        return steering_text

    def build_correction_request(
        self,
        request: ChatRequest,
        assistant_response: Any,
        steering_message: str,
    ) -> ChatRequest:
        normalized_response = self._normalize_assistant_content(assistant_response)
        steering_text = self.build_steering_payload(steering_message)

        augmented_messages = [
            *list(request.messages),
            ChatMessage(role="assistant", content=normalized_response),
            ChatMessage(role="system", content=steering_text),
        ]

        return request.model_copy(
            update={
                "messages": augmented_messages,
                "stream": False,
            }
        )

    def parse_angel_output(self, text: str) -> AngelDecision:
        # Pass decision
        if re.search(
            r"<angels_decision>\s*Pass\s*</angels_decision>", text, re.IGNORECASE
        ):
            return AngelDecision(decision="pass")
        # Steering message
        m = re.search(
            r"<angels_steering_message>([\s\S]*?)</angels_steering_message>",
            text,
            re.IGNORECASE,
        )
        if m:
            msg = m.group(1).strip()
            return AngelDecision(decision="steer", steering_message=msg)
        # Default to pass if no recognizable XML
        return AngelDecision(decision="pass")

    def has_override_marker(self, text: str) -> bool:
        return bool(self._OVERRIDE_RE.search(text))

    def strip_override_marker(self, text: str) -> str:
        return self._OVERRIDE_RE.sub("", text)
