"""Integration tests for capture collaborator boundary contracts.

These tests verify that capture collaborator interfaces enforce canonical
typed contracts (CanonicalUsageRecord, dict[str, JsonValue]) at boundaries.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic.types import JsonValue
from src.core.domain.request_context import RequestContext
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
)
from src.core.interfaces.backend_completion_collaborators import (
    IWireCaptureOrchestrator,
)
from src.core.interfaces.wire_capture_interface import IWireCapture


class MockWireCapture(IWireCapture):
    """Mock wire capture that records calls for verification."""

    def __init__(self) -> None:
        self.capture_inbound_response_calls: list[dict[str, Any]] = []
        self.capture_stream_completion_calls: list[dict[str, Any]] = []
        self._enabled = True

    def enabled(self) -> bool:
        return self._enabled

    async def capture_inbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        request_payload: Any,
        raw_body: bytes | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        pass

    async def capture_outbound_request(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        request_payload: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        pass

    async def capture_inbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Record call with typed canonical_usage parameter."""
        self.capture_inbound_response_calls.append(
            {
                "canonical_usage": canonical_usage,
                "canonical_usage_type": (
                    type(canonical_usage).__name__ if canonical_usage else None
                ),
            }
        )

    def wrap_inbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        stream: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> Any:
        return stream

    async def capture_outbound_response(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        pass

    def wrap_outbound_stream(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str | None,
        model: str | None,
        key_name: str | None,
        stream: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> Any:
        return stream

    async def capture_stream_completion(
        self,
        *,
        context: RequestContext | None,
        session_id: str | None,
        backend: str,
        model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Record call with typed eos_metadata parameter."""
        self.capture_stream_completion_calls.append(
            {
                "eos_metadata": eos_metadata,
                "eos_metadata_type": (
                    type(eos_metadata).__name__ if eos_metadata else None
                ),
            }
        )

    async def shutdown(self) -> None:
        pass


class MockWireCaptureOrchestrator(IWireCaptureOrchestrator):
    """Mock orchestrator that records calls for verification."""

    def __init__(self, wire_capture: IWireCapture) -> None:
        self._wire_capture = wire_capture
        self.capture_inbound_response_calls: list[dict[str, Any]] = []
        self.capture_stream_completion_calls: list[dict[str, Any]] = []

    async def prepare_wire_capture_context(
        self, backend_type: str, session: Any | None
    ) -> Any | None:
        return None

    async def capture_wire_outbound(
        self,
        backend_type: str,
        effective_model: str,
        domain_request: Any,
        context: RequestContext | None,
    ) -> None:
        pass

    def detect_key_name(self, backend_type: str) -> str | None:
        return None

    async def capture_inbound_response(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        response_content: dict[str, JsonValue] | bytes | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Record call with typed canonical_usage parameter."""
        self.capture_inbound_response_calls.append(
            {
                "canonical_usage": canonical_usage,
                "canonical_usage_type": (
                    type(canonical_usage).__name__ if canonical_usage else None
                ),
            }
        )
        await self._wire_capture.capture_inbound_response(
            context=context,
            session_id=session_id,
            backend=backend_type,
            model=effective_model,
            key_name=key_name,
            response_content=response_content,
            canonical_usage=canonical_usage,
            capture_metadata=capture_metadata,
        )

    def wrap_inbound_stream(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        stream: Any,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> Any:
        return stream

    async def capture_stream_completion(
        self,
        context: RequestContext | None,
        session_id: str | None,
        backend_type: str,
        effective_model: str,
        key_name: str | None,
        canonical_usage: CanonicalUsageRecord | None = None,
        eos_metadata: dict[str, JsonValue] | None = None,
        capture_metadata: dict[str, JsonValue] | None = None,
    ) -> None:
        """Record call with typed eos_metadata parameter."""
        self.capture_stream_completion_calls.append(
            {
                "eos_metadata": eos_metadata,
                "eos_metadata_type": (
                    type(eos_metadata).__name__ if eos_metadata else None
                ),
            }
        )
        await self._wire_capture.capture_stream_completion(
            context=context,
            session_id=session_id,
            backend=backend_type,
            model=effective_model,
            key_name=key_name,
            canonical_usage=canonical_usage,
            eos_metadata=eos_metadata,
            capture_metadata=capture_metadata,
        )


@pytest.mark.asyncio
async def test_capture_inbound_response_accepts_canonical_usage_record() -> None:
    """Verify IWireCapture.capture_inbound_response accepts CanonicalUsageRecord."""
    mock_capture = MockWireCapture()
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    usage = CanonicalUsageRecord(
        provider_id="openai",
        model_id="gpt-4",
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
    )

    await mock_capture.capture_inbound_response(
        context=ctx,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content={"choices": []},
        canonical_usage=usage,
    )

    assert len(mock_capture.capture_inbound_response_calls) == 1
    call = mock_capture.capture_inbound_response_calls[0]
    assert call["canonical_usage"] == usage
    assert call["canonical_usage_type"] == "CanonicalUsageRecord"


@pytest.mark.asyncio
async def test_capture_inbound_response_accepts_none_usage() -> None:
    """Verify IWireCapture.capture_inbound_response accepts None for canonical_usage."""
    mock_capture = MockWireCapture()
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    await mock_capture.capture_inbound_response(
        context=ctx,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content={"choices": []},
        canonical_usage=None,
    )

    assert len(mock_capture.capture_inbound_response_calls) == 1
    call = mock_capture.capture_inbound_response_calls[0]
    assert call["canonical_usage"] is None


@pytest.mark.asyncio
async def test_capture_stream_completion_accepts_json_safe_eos_metadata() -> None:
    """Verify IWireCapture.capture_stream_completion accepts dict[str, JsonValue]."""
    mock_capture = MockWireCapture()
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    eos_metadata: dict[str, JsonValue] = {
        "eos": True,
        "eos_signal": "done",
        "eos_reason": "stop",
        "eos_termination_category": "complete",
        "eos_error_status_code": 200,
    }

    await mock_capture.capture_stream_completion(
        context=ctx,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        canonical_usage=None,
        eos_metadata=eos_metadata,
    )

    assert len(mock_capture.capture_stream_completion_calls) == 1
    call = mock_capture.capture_stream_completion_calls[0]
    assert call["eos_metadata"] == eos_metadata
    assert call["eos_metadata_type"] == "dict"


@pytest.mark.asyncio
async def test_capture_stream_completion_accepts_none_eos_metadata() -> None:
    """Verify IWireCapture.capture_stream_completion accepts None for eos_metadata."""
    mock_capture = MockWireCapture()
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    usage = CanonicalUsageRecord(
        provider_id="openai",
        model_id="gpt-4",
        prompt_tokens=10,
        completion_tokens=20,
    )

    await mock_capture.capture_stream_completion(
        context=ctx,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        canonical_usage=usage,
        eos_metadata=None,
    )

    assert len(mock_capture.capture_stream_completion_calls) == 1
    call = mock_capture.capture_stream_completion_calls[0]
    assert call["eos_metadata"] is None


@pytest.mark.asyncio
async def test_orchestrator_capture_inbound_response_passes_canonical_usage() -> None:
    """Verify IWireCaptureOrchestrator passes CanonicalUsageRecord to IWireCapture."""
    mock_capture = MockWireCapture()
    orchestrator = MockWireCaptureOrchestrator(mock_capture)
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    usage = CanonicalUsageRecord(
        provider_id="anthropic",
        model_id="claude-3",
        prompt_tokens=15,
        completion_tokens=25,
    )

    await orchestrator.capture_inbound_response(
        context=ctx,
        session_id="test-session",
        backend_type="anthropic",
        effective_model="claude-3",
        key_name="ANTHROPIC_API_KEY",
        response_content={"content": []},
        canonical_usage=usage,
    )

    # Verify orchestrator recorded the call
    assert len(orchestrator.capture_inbound_response_calls) == 1
    assert orchestrator.capture_inbound_response_calls[0]["canonical_usage"] == usage

    # Verify mock capture received the call
    assert len(mock_capture.capture_inbound_response_calls) == 1
    assert mock_capture.capture_inbound_response_calls[0]["canonical_usage"] == usage


@pytest.mark.asyncio
async def test_orchestrator_capture_stream_completion_passes_json_safe_metadata() -> (
    None
):
    """Verify IWireCaptureOrchestrator passes dict[str, JsonValue] to IWireCapture."""
    mock_capture = MockWireCapture()
    orchestrator = MockWireCaptureOrchestrator(mock_capture)
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    eos_metadata: dict[str, JsonValue] = {
        "eos": True,
        "eos_signal": "stop",
        "eos_reason": "max_tokens",
    }

    await orchestrator.capture_stream_completion(
        context=ctx,
        session_id="test-session",
        backend_type="openai",
        effective_model="gpt-4",
        key_name="OPENAI_API_KEY",
        canonical_usage=None,
        eos_metadata=eos_metadata,
    )

    # Verify orchestrator recorded the call
    assert len(orchestrator.capture_stream_completion_calls) == 1
    assert (
        orchestrator.capture_stream_completion_calls[0]["eos_metadata"] == eos_metadata
    )

    # Verify mock capture received the call
    assert len(mock_capture.capture_stream_completion_calls) == 1
    assert (
        mock_capture.capture_stream_completion_calls[0]["eos_metadata"] == eos_metadata
    )


@pytest.mark.asyncio
async def test_eos_metadata_json_safety() -> None:
    """Verify eos_metadata only accepts JSON-serializable values."""
    mock_capture = MockWireCapture()
    ctx = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    # Valid JSON-safe metadata
    valid_metadata: dict[str, JsonValue] = {
        "eos": True,
        "eos_signal": "done",
        "eos_reason": "stop",
        "eos_error_status_code": 200,
        "nested": {"key": "value", "number": 42},
        "list": [1, 2, 3],
    }

    await mock_capture.capture_stream_completion(
        context=ctx,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        canonical_usage=None,
        eos_metadata=valid_metadata,
    )

    assert len(mock_capture.capture_stream_completion_calls) == 1
    call = mock_capture.capture_stream_completion_calls[0]
    assert call["eos_metadata"] == valid_metadata
