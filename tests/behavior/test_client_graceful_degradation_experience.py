"""
Client-facing graceful degradation behavior tests targeting the new fallback flow.

These scenarios focus on observable outcomes (response timing, fallback selection,
and metrics) rather than the legacy streaming harness that no longer matches the
connector internals.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, AsyncMock

import httpx
import pytest
from src.connectors.gemini_oauth_base import (
    GeminiOAuthBaseConnector,
    GracefulDegradationConfig,
    GracefulDegradationMetrics,
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
        self._graceful_metrics = GracefulDegradationMetrics()

        self._behavior: dict[str, list[Any]] = {}
        self._call_count: dict[str, int] = {}

        # Speed up retries for tests while still exercising delay logic.
        self._degradation_config = GracefulDegradationConfig(
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
                    "created": int(time.time()),
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


@pytest.mark.asyncio
async def test_immediate_fallback_returns_flash_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = ClientExperienceConnector()
    connector.set_behavior(
        "gemini-2.5-pro",
        [
            BackendError("Rate limit", status_code=429),
        ],
    )
    connector.set_behavior("gemini-2.5-flash", ["flash-response"])

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    start = time.time()
    response = await connector._handle_429_with_graceful_degradation(
        original_model="gemini-2.5-pro",
        request_data=_canonical_request(),
        processed_messages=[],
    )
    elapsed = time.time() - start

    assert isinstance(response, ResponseEnvelope)
    assert response.content.content == "flash-response"  # type: ignore[attr-defined]
    assert connector._call_count["gemini-2.5-pro"] == 1
    assert connector._call_count["gemini-2.5-flash"] == 1
    metrics = connector.get_graceful_degradation_metrics()
    assert metrics["fallback_invocations"] == 1
    # Initial 2s delay per model to prevent burst rate limiting (+ jitter)
    # gemini-2.5-pro ~2s + gemini-2.5-flash ~2s = ~4s total
    assert elapsed < 6.0


@pytest.mark.asyncio
async def test_flash_failure_marks_backend_unusable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = ClientExperienceConnector()
    rate_limit = BackendError("Rate limit", status_code=429)
    connector.set_behavior("gemini-2.5-pro", [rate_limit])
    connector.set_behavior("gemini-2.5-flash", [rate_limit, rate_limit, rate_limit])

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    with pytest.raises(BackendError) as exc:
        await connector._handle_429_with_graceful_degradation(
            original_model="gemini-2.5-pro",
            request_data=_canonical_request(),
            processed_messages=[],
        )

    assert exc.value.code == "models_rate_limited"
    assert connector._permanently_failed
    assert not connector.is_backend_functional()


@pytest.mark.asyncio
async def test_metrics_capture_wait_time_and_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = ClientExperienceConnector()
    connector._degradation_config.retry_delays = [0.05]
    rate_limit = BackendError("Rate", status_code=429)
    connector.set_behavior("gemini-2.5-pro", [rate_limit])
    connector.set_behavior("gemini-2.5-flash", [rate_limit, "recovered"])

    wait_times: list[float] = []

    async def fake_sleep_impl(delay: float) -> None:
        wait_times.append(delay)

    monkeypatch.setattr(asyncio, "sleep", AsyncMock(side_effect=fake_sleep_impl))

    await connector._handle_429_with_graceful_degradation(
        original_model="gemini-2.5-pro",
        request_data=_canonical_request(),
        processed_messages=[],
    )

    metrics = connector.get_graceful_degradation_metrics()
    assert wait_times  # ensure we recorded at least one delay
    assert metrics["total_wait_time"] == pytest.approx(sum(wait_times))
    assert metrics["total_attempts"] >= 2  # pro attempt + fallback
    assert metrics["last_duration"] >= 0.0


@pytest.mark.asyncio
async def test_streaming_envelope_carries_fallback_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = ClientExperienceConnector()
    connector.set_behavior("gemini-2.5-pro", [BackendError("limit", status_code=429)])
    connector.set_behavior("gemini-2.5-flash", ["streamed-response"])

    # Mock sleep to avoid real delay
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())

    envelope = await connector._handle_429_with_graceful_degradation(
        original_model="gemini-2.5-pro",
        request_data=_canonical_request(),
        processed_messages=[],
    )

    assert isinstance(envelope, ResponseEnvelope)

    stream_envelope = await connector._chat_completions_code_assist_streaming(
        request_data=_canonical_request(),
        processed_messages=[],
        effective_model="gemini-2.5-pro",
    )
    assert isinstance(stream_envelope, StreamingResponseEnvelope)

    collected = []

    async for chunk in stream_envelope.content:  # type: ignore[union-attr]
        collected.append(chunk.content["choices"][0]["delta"].get("content"))

    assert "streamed-response" in collected
