"""Integration tests for the Responses API WebSocket endpoint."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.responses_session_store_interface import IResponsesSessionStore

pytestmark = pytest.mark.integration


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


def test_websocket_multi_turn_previous_response_id_round_trip(
    app: FastAPI, client: TestClient
) -> None:
    response_one = ResponseEnvelope(
        content={
            "id": "resp-ws-turn-1",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "msg-ws-turn-1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "First websocket"}],
                }
            ],
        },
        status_code=200,
    )
    response_two = ResponseEnvelope(
        content={
            "id": "resp-ws-turn-2",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "msg-ws-turn-2",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Second websocket"}],
                }
            ],
        },
        status_code=200,
    )

    with (
        patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            side_effect=[response_one, response_two],
        ),
        client.websocket_connect(
            "/v1/responses",
            headers={"x-request-id": "ws-round-trip"},
        ) as websocket,
    ):
        websocket.send_json(
            {
                "type": "response.create",
                "model": "mock-model",
                "input": "First websocket turn",
            }
        )
        first_event = websocket.receive_json()
        assert first_event["type"] == "response.done"
        first_response_id = first_event["response"]["id"]

        store = app.state.service_provider.get_required_service(IResponsesSessionStore)
        resolved = asyncio.run(store.resolve(first_response_id))
        assert resolved is not None
        assert resolved.output_items[0].id == "msg-ws-turn-1"

        websocket.send_json(
            {
                "type": "response.create",
                "model": "mock-model",
                "input": "Second websocket turn",
                "previous_response_id": first_response_id,
            }
        )
        second_event = websocket.receive_json()

    assert second_event["type"] == "response.done"
    assert second_event["response"]["id"] == "resp-ws-turn-2"
