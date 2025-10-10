from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import Session
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.request_processor_service import RequestProcessor


@pytest.mark.asyncio
async def test_request_processor_uses_app_state_command_prefix(monkeypatch) -> None:
    app_state = ApplicationStateService()
    app_state.set_command_prefix("$/")
    app_state.set_setting(
        "app_config",
        SimpleNamespace(
            auth=SimpleNamespace(redact_api_keys_in_prompts=True),
            command_prefix="!/",
        ),
    )

    class DummyCommandProcessor:
        async def process_messages(self, messages, session_id, context):
            return ProcessedResult(
                modified_messages=messages,
                command_executed=False,
                command_results=[],
            )

    class DummySessionManager:
        async def resolve_session_id(self, context):
            return "session-123"

        async def get_session(self, session_id):
            return Session(session_id=session_id)

        async def update_session_agent(self, session, agent):
            return session

        async def record_command_in_session(self, request, session_id):
            return None

        async def update_session_history(
            self, request_data, backend_request, backend_response, session_id
        ):
            return None

    class DummyBackendRequestManager:
        async def prepare_backend_request(self, request_data, command_result):
            return request_data

        async def process_backend_request(self, backend_request, session_id, context):
            return ResponseEnvelope(content={"ok": True})

    class DummyResponseManager:
        async def process_command_result(self, command_result, session):
            return ResponseEnvelope(content={"command": True})

    captured_prefix: dict[str, str] = {}

    async def _echo_process(request, _context):
        return request

    def fake_redaction(*, api_keys, command_prefix):
        captured_prefix["value"] = command_prefix
        middleware = MagicMock()
        middleware.process = AsyncMock(side_effect=_echo_process)
        return middleware

    monkeypatch.setattr(
        "src.core.services.redaction_middleware.RedactionMiddleware",
        fake_redaction,
    )
    monkeypatch.setattr(
        "src.core.common.logging_utils.discover_api_keys_from_config_and_env",
        lambda cfg: [],
    )
    monkeypatch.setattr(
        "src.core.config.edit_precision_temperatures.load_edit_precision_temperatures_config",
        dict,
    )

    class DummyEditPrecision:
        async def process(self, request, context):
            return request

    monkeypatch.setattr(
        "src.core.services.edit_precision_middleware.EditPrecisionTuningMiddleware",
        lambda *args, **kwargs: DummyEditPrecision(),
    )

    processor = RequestProcessor(
        command_processor=DummyCommandProcessor(),
        session_manager=DummySessionManager(),
        backend_request_manager=DummyBackendRequestManager(),
        response_manager=DummyResponseManager(),
        app_state=app_state,
    )

    request = ChatRequest(
        model="gpt-test",
        messages=[ChatMessage(role="user", content="Hello")],
    )
    context = RequestContext(headers={}, cookies={}, state={}, app_state=None)

    await processor.process_request(context, request)

    assert captured_prefix.get("value") == "$/"
