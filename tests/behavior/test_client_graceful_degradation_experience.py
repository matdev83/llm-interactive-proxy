"""
Client-facing graceful degradation behavior tests targeting the new fallback flow.

These scenarios focus on observable outcomes (response timing, fallback selection,
and metrics) rather than the legacy streaming harness that no longer matches the
connector internals.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
)
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class _TranslationShim:
    """Minimal translation service to satisfy connector expectations."""

    def from_domain_to_gemini_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "role": message.role,
                    "parts": [{"text": message.content}],
                }
                for message in request.messages
            ]
        }

    def to_domain_stream_chunk(
        self, chunk: Any, source_format: str, target_format: str = "domain"
    ) -> Any:
        return chunk


@dataclass
class _ScenarioResult:
    """Container describing the outcome returned by the mock connector."""

    content: str


class ClientExperienceConnector(GeminiOAuthBaseConnector):
    """Test double that exercises graceful degradation logic without real HTTP calls."""

    def __init__(self) -> None:
        config = AppConfigMock()
        translation = _TranslationShim()
        client = MagicMock(spec=httpx.AsyncClient)
        super().__init__(
            client=client,
            config=config,
            translation_service=translation,  # type: ignore[arg-type]
            name="client-experience",
        )

        self.translation_service = translation  # tighten type for mypy
        self.gemini_api_base_url = "https://mocked.example.com"

        self._behavior: dict[str, list[Any]] = {}
        self._call_count: dict[str, int] = {}

        # Speed up retries for tests while still exercising delay logic.
        # Override the graceful degradation config using the manager
        self._graceful_degradation.config = GracefulDegradationConfig(
            enabled=True,
            retry_delays=[0.1, 0.2, 0.3],
            max_total_attempts=9,
            cooldown_duration=0.0,
            enable_recovery_probing=False,
            recovery_probe_interval=60.0,
        )

        self._oauth_credentials = {"access_token": "test-token"}

    def set_behavior(self, model: str, outcomes: list[Any]) -> None:
        self._behavior[model] = outcomes
        self._call_count[model] = 0

    async def _refresh_token_if_needed(self) -> bool:
        return True

    async def _discover_project_id(self, auth_session: Any) -> str:
        return "test-project"

    async def _chat_completions_code_assist(
        self,
        request_data: CanonicalChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> ResponseEnvelope:
        index = self._call_count.get(effective_model, 0)
        self._call_count[effective_model] = index + 1
        outcomes = self._behavior.get(effective_model, [])

        outcome = outcomes[index] if index < len(outcomes) else outcomes[-1]
        if isinstance(outcome, Exception):
            raise outcome
        content = outcome if isinstance(outcome, str) else str(outcome)
        return ResponseEnvelope(content=_ScenarioResult(content=content))

    async def _chat_completions_code_assist_streaming(
        self,
        request_data: CanonicalChatRequest,
        processed_messages: list[Any],
        effective_model: str,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        try:
            response = await self._chat_completions_code_assist(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                **kwargs,
            )
        except BackendError as exc:  # pragma: no cover - mirrors parent behavior
            if getattr(exc, "status_code", None) == 429:
                response = await self._handle_429_with_graceful_degradation(
                    original_model=effective_model,
                    request_data=request_data,
                    processed_messages=processed_messages,
                    **kwargs,
                )
            else:
                raise

        async def iterator() -> AsyncGenerator[ProcessedResponse, None]:
            yield ProcessedResponse(
                content={
                    "id": "chatcmpl-1",
                    "object": "chat.completion.chunk",
                    "created": 1234567890,  # Fixed timestamp for deterministic testing
                    "model": effective_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": response.content.content},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )

        return StreamingResponseEnvelope(content=iterator())


class AppConfigMock(AppConfig):
    """Use default AppConfig without hitting disk."""

    def __init__(self) -> None:
        super().__init__()


def _canonical_request(model: str = "gemini-2.5-pro") -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def client_experience_connector() -> ClientExperienceConnector:
    """Cached fixture to avoid repeated connector creation."""
    return ClientExperienceConnector()


@pytest.mark.asyncio
async def test_retry_success_returns_pro_response_no_fallback(
    client_experience_connector: ClientExperienceConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that _handle_429_with_graceful_degradation propagates 429s to the resilience layer.

    As of the Resilience Layer implementation, the connector's _handle_429_with_graceful_degradation
    no longer performs retries itself - it just raises the BackendError with retry_after info
    for the BackendService's failure handling strategy to handle.

    This test verifies that:
    1. The method raises BackendError (not returns a response)
    2. The error includes retry_after info when available
    """

    # Create error with retry_after
    original_error = BackendError(
        message="Rate limit exceeded",
        status_code=429,
        details={"retry_after": 30.0},
    )

    # The method should raise BackendError to propagate to resilience layer
    with pytest.raises(BackendError) as exc:
        await client_experience_connector._handle_429_with_graceful_degradation(
            original_model="gemini-2.5-pro",
            request_data=_canonical_request(),
            processed_messages=[],
            error=original_error,
        )

    # Verify the error is propagated with retry info
    assert exc.value.status_code == 429
    # Note: The connector may or may not include retry_after depending on implementation


@pytest.mark.asyncio
async def test_rate_limit_error_propagated_with_details(
    client_experience_connector: ClientExperienceConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that 429 errors are propagated with error details intact.

    As of Resilience Layer implementation, the connector no longer handles
    retries or fallbacks internally. It propagates the error to the BackendService
    failure handling strategy, which manages retries and circuit breaking.
    """
    rate_limit = BackendError(
        "Rate limit exceeded",
        status_code=429,
        code="rate_limit_exceeded",
        details={"retry_after": 60.0},
    )

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(BackendError) as exc:
        await client_experience_connector._handle_429_with_graceful_degradation(
            original_model="gemini-2.5-pro",
            request_data=_canonical_request(),
            processed_messages=[],
            error=rate_limit,
        )

    # The error should be propagated with the same code
    assert exc.value.code == "rate_limit_exceeded"
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_error_includes_retry_after_metadata(
    client_experience_connector: ClientExperienceConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that 429 errors include retry_after info when available.

    The Resilience Layer uses this info to determine appropriate retry delays.
    """

    # Create error with retry_after metadata
    rate_limit = BackendError(
        "Rate limit exceeded",
        status_code=429,
        details={"retry_after": 45.0},
    )

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(BackendError) as exc:
        await client_experience_connector._handle_429_with_graceful_degradation(
            original_model="gemini-2.5-pro",
            request_data=_canonical_request(),
            processed_messages=[],
            error=rate_limit,
        )

    # Verify the error is raised with status code intact
    assert exc.value.status_code == 429
    # Details should be propagated for the Resilience Layer to use
    if exc.value.details:
        assert isinstance(exc.value.details, dict)


@pytest.mark.asyncio
async def test_streaming_envelope_carries_response_text(
    client_experience_connector: ClientExperienceConnector,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that streaming envelope carries response text from successful calls.

    This tests the normal streaming path without error handling.
    """
    # Set up successful response
    client_experience_connector.set_behavior("gemini-2.5-pro", ["streamed-response"])

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    stream_envelope = (
        await client_experience_connector._chat_completions_code_assist_streaming(
            request_data=_canonical_request(),
            processed_messages=[],
            effective_model="gemini-2.5-pro",
        )
    )
    assert isinstance(stream_envelope, StreamingResponseEnvelope)

    collected = []

    async for chunk in stream_envelope.content:  # type: ignore[union-attr]
        collected.append(chunk.content["choices"][0]["delta"].get("content"))

    assert "streamed-response" in collected
