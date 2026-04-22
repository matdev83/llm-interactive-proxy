"""Regression tests for Responses session store wiring on completed payloads."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.controllers.responses_controller import ResponsesController


@pytest.fixture
def mock_processor() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_translation_service() -> MagicMock:
    service = MagicMock()
    service.to_domain_request = MagicMock()
    service.from_domain_response = MagicMock()
    return service


@pytest.mark.asyncio
async def test_store_completed_responses_payload_logs_skipped_invalid_output(
    mock_processor: AsyncMock,
    mock_translation_service: MagicMock,
    responses_controller_backend_deps: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid output[] elements must be visible in logs when skipped for session linkage."""
    caplog.set_level(
        logging.WARNING,
        logger="src.core.app.controllers.responses_controller",
    )
    controller = ResponsesController(
        request_processor=mock_processor,
        translation_service=mock_translation_service,
        **responses_controller_backend_deps,
    )
    payload = {
        "id": "resp_store_log",
        "output": [
            {
                "id": "ok_1",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [],
            },
            {"invalid": "shape"},
        ],
    }
    await controller._store_completed_responses_payload(
        payload,
        instructions=None,
    )
    assert any(
        "resp_store_log" in r.message and "skipping invalid output" in r.message.lower()
        for r in caplog.records
        if r.levelno >= logging.WARNING
    )
