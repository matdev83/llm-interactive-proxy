"""Phase 8 integration and contract tests for Responses API frontend compliance."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic.types import JsonValue
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.responses_native_wiring import (
    RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.responses_session_store_interface import IResponsesSessionStore

pytestmark = pytest.mark.integration

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "responses_api_frontend"


def _load_fixture(name: str) -> dict[str, object]:
    payload = json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))
    return cast(dict[str, object], payload)


def _parse_sse_payloads(body: str) -> tuple[list[dict[str, object]], list[str]]:
    events: list[dict[str, object]] = []
    sentinels: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        raw = line[len("data: ") :].strip()
        if raw == "[DONE]":
            sentinels.append(raw)
            continue
        events.append(json.loads(raw))
    return events, sentinels


def _collect_websocket_events(
    websocket: Any,
    *,
    terminal_type: str,
    limit: int = 16,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for _ in range(limit):
        event = websocket.receive_json()
        assert isinstance(event, dict)
        events.append(event)
        if event.get("type") == terminal_type:
            break
    assert events[-1].get("type") == terminal_type
    return events


@pytest.fixture
def app_config() -> AppConfig:
    backend_settings = BackendSettings(default_backend="mock").model_copy(
        update={
            "openai": BackendConfig(api_key="test-openai-key"),
            "anthropic": BackendConfig(api_key="test-anthropic-key"),
        }
    )
    return AppConfig(
        host="localhost",
        port=8000,
        command_prefix="!/",
        backends=backend_settings,
        auth=AuthConfig(
            disable_auth=True,
            api_keys=[],
            redact_api_keys_in_prompts=False,
        ),
    )


@pytest.fixture
def app(app_config: AppConfig) -> FastAPI:
    from src.core.app.test_builder import build_test_app

    return build_test_app(app_config)


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


class TestResponsesAPIPhase8Contracts:
    def test_http_streaming_matches_pinned_fixture(self, client: TestClient) -> None:
        fixture = _load_fixture("http_streaming_sse.json")
        request_data = {
            "model": "mock-model",
            "input": "Stream a canonical response",
            "stream": True,
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:

            async def mock_stream() -> AsyncGenerator[ProcessedResponse, None]:
                for event in cast(list[object], fixture["events"]):
                    yield ProcessedResponse(content=cast(dict[str, JsonValue], event))

            mock_process.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                headers={"content-type": "text/event-stream"},
                media_type="text/event-stream",
            )

            with client.stream("POST", "/v1/responses", json=request_data) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")
                body = b"".join(response.iter_bytes()).decode("utf-8")

        events, sentinels = _parse_sse_payloads(body)
        assert events == fixture["events"]
        assert sentinels == [fixture["done"]]

    def test_http_previous_response_id_resolves_across_requests(
        self, app: FastAPI, client: TestClient
    ) -> None:
        request_one = {
            "model": "mock-model",
            "input": "First turn",
        }
        request_two = {
            "model": "mock-model",
            "input": "Second turn",
            "previous_response_id": "resp-turn-1",
        }
        response_one = ResponseEnvelope(
            content={
                "id": "resp-turn-1",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg-turn-1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "First reply"}],
                    }
                ],
            },
            status_code=200,
        )
        response_two = ResponseEnvelope(
            content={
                "id": "resp-turn-2",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg-turn-2",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "Second reply"}],
                    }
                ],
            },
            status_code=200,
        )

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            side_effect=[response_one, response_two],
        ) as mock_process:
            first = client.post("/v1/responses", json=request_one)
            assert first.status_code == 200

            store = app.state.service_provider.get_required_service(
                IResponsesSessionStore
            )
            resolved = asyncio.run(store.resolve("resp-turn-1"))
            assert resolved is not None
            assert resolved.output_items[0].id == "msg-turn-1"

            second = client.post(
                "/v1/responses",
                json=request_two,
                headers={"x-request-id": "req-multi-turn"},
            )

        assert second.status_code == 200
        assert mock_process.call_count == 2

        second_request = mock_process.call_args_list[1].args[1]
        native_payload = second_request.extra_body[
            RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY
        ]
        assert native_payload["previous_response_id"] == "resp-turn-1"

    def test_http_provider_limitation_and_request_id_match_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("http_provider_limitation_error.json")
        response = client.post(
            "/v1/responses",
            headers={"x-request-id": "req-provider-limit"},
            json={
                "model": "anthropic:claude-3-5-sonnet-20241022",
                "input": "Hello",
                "include": ["reasoning.encrypted_content"],
            },
        )

        assert response.status_code == 400
        assert response.json() == fixture

    def test_http_provider_limitation_gemini_matches_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("http_provider_limitation_gemini.json")
        response = client.post(
            "/v1/responses",
            headers={"x-request-id": "req-provider-limit-gemini"},
            json={
                "model": "gemini:gemini-1.5-flash",
                "input": "Hello",
                "include": ["reasoning.encrypted_content"],
            },
        )

        assert response.status_code == 400
        assert response.json() == fixture

    def test_http_native_wire_payload_preserves_typed_input_items(
        self, client: TestClient
    ) -> None:
        typed_input: list[dict[str, object]] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Hi"}],
            }
        ]
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            mock_process.return_value = ResponseEnvelope(
                content={
                    "id": "resp-native-items",
                    "object": "response",
                    "status": "completed",
                    "output": [],
                },
                status_code=200,
            )
            response = client.post(
                "/v1/responses",
                json={"model": "mock-model", "input": typed_input},
            )

        assert response.status_code == 200
        assert mock_process.call_count == 1
        forwarded = mock_process.call_args.args[1]
        native_payload = forwarded.extra_body[RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY]
        assert isinstance(native_payload, dict)
        assert native_payload.get("input") == typed_input
        assert "messages" not in native_payload

    def test_websocket_streaming_matches_pinned_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("websocket_streaming.json")

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:

            async def mock_stream() -> AsyncGenerator[ProcessedResponse, None]:
                for event in cast(list[object], fixture["upstream_events"]):
                    yield ProcessedResponse(content=cast(dict[str, JsonValue], event))

            mock_process.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                headers={},
                media_type="text/event-stream",
            )

            with client.websocket_connect(
                "/v1/responses",
                headers={"x-request-id": "ws-contract-1"},
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "response.create",
                        "model": "mock-model",
                        "input": "Hello websocket",
                        "stream": True,
                    }
                )
                events = _collect_websocket_events(
                    websocket,
                    terminal_type="response.done",
                )

        assert mock_process.called
        assert events == fixture["frontend_events"]

    def test_websocket_invalid_json_matches_pinned_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("websocket_invalid_json_error.json")

        with client.websocket_connect(
            "/v1/responses",
            headers={"x-request-id": "ws-invalid-json"},
        ) as websocket:
            websocket.send_text("not valid json")
            event = websocket.receive_json()

        assert event == fixture

    def test_websocket_unsupported_event_matches_pinned_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("websocket_unsupported_event_error.json")

        with client.websocket_connect(
            "/v1/responses",
            headers={"x-request-id": "ws-unsupported-event"},
        ) as websocket:
            websocket.send_json({"type": "unsupported.event"})
            event = websocket.receive_json()

        assert event == fixture

    def test_websocket_previous_response_not_found_matches_pinned_fixture(
        self, client: TestClient
    ) -> None:
        fixture = _load_fixture("websocket_previous_response_not_found_error.json")

        with client.websocket_connect(
            "/v1/responses",
            headers={"x-request-id": "ws-missing-previous"},
        ) as websocket:
            websocket.send_json(
                {
                    "type": "response.create",
                    "model": "mock-model",
                    "input": "Follow-up",
                    "previous_response_id": "resp-missing",
                }
            )
            event = websocket.receive_json()

        assert event == fixture
