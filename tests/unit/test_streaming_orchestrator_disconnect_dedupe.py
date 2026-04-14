"""Burst deduplication for client-disconnect DEBUG logs on shared stream_id."""

import logging
import uuid

import pytest
from src.core.ports import streaming_orchestrator as orchestrator_module


def test_client_disconnect_debug_emitted_once_per_burst(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    sid = f"dedupe-test-{uuid.uuid4().hex}"
    orchestrator_module._emit_client_disconnect_debug("openai", sid)
    orchestrator_module._emit_client_disconnect_debug("openai", sid)
    orchestrator_module._emit_client_disconnect_debug("openai", sid)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage() == "Client disconnected during streaming"
    ]
    assert len(lines) == 1


def test_client_disconnect_debug_distinct_stream_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    a = f"a-{uuid.uuid4().hex}"
    b = f"b-{uuid.uuid4().hex}"
    orchestrator_module._emit_client_disconnect_debug("openai", a)
    orchestrator_module._emit_client_disconnect_debug("openai", b)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage() == "Client disconnected during streaming"
    ]
    assert len(lines) == 2


def test_client_disconnect_debug_distinct_providers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    sid = f"shared-{uuid.uuid4().hex}"
    orchestrator_module._emit_client_disconnect_debug("openai", sid)
    orchestrator_module._emit_client_disconnect_debug("anthropic", sid)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage() == "Client disconnected during streaming"
    ]
    assert len(lines) == 2
