from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.migration_gate_service import MigrationGateService

from tests.helpers.backend_request_manager_fixtures import (
    create_backend_request_manager,
)


@pytest.mark.asyncio
async def test_backend_request_manager_records_path_selection_diagnostics() -> None:
    backend_processor = MagicMock()
    backend_processor.process_backend_request = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    manager = create_backend_request_manager(backend_processor=backend_processor)
    manager._migration_gate_service = MigrationGateService.from_flags(
        enable_core_canonical_path=False,
        emit_path_selection_metadata=True,
    )

    coordinator = cast(Any, manager._post_backend_response_coordinator)

    async def _mock_stream(
        *, stream: Any, **__: Any
    ) -> StreamingResponseEnvelope:
        async def _one() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content={"ok": True})

        return StreamingResponseEnvelope(content=_one(), media_type="application/json")

    coordinator._streaming_handler.handle = AsyncMock(side_effect=_mock_stream)

    request = ChatRequest(
        model="gpt-4o-mini",
        messages=[ChatMessage(role="user", content="hello")],
        stream=False,
    )
    context = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    _ = await manager.process_backend_request(request, "sess-1", context)

    assert context.extensions["migration_stage"] == "canonical_runtime"
    assert context.extensions["canonical_path_used"] is True
    assert context.extensions["selected_processing_path"] == "canonical_core"
    promo = context.extensions.get("promotion_guardrails")
    assert isinstance(promo, dict)
    assert promo.get("strict_missing_evidence") is True
    assert promo.get("overall_passed") is False
