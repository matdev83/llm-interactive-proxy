"""Regression tests for Responses API frontend compliance bugs (session store, OpenAI delegation, shorthand)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Generator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic.types import JsonValue
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorResponsesRequest,
)
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import ResponsesValidationError
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.responses_native_wiring import (
    RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY,
)
from src.core.domain.responses_request_normalizer import ResponsesRequestNormalizer
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.responses_session_store_interface import IResponsesSessionStore
from src.core.services.translation_service import TranslationService

pytestmark = [pytest.mark.regression]

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "integration"
    / "fixtures"
    / "responses_api_frontend"
)


def _load_sse_fixture_streaming_events() -> list[dict[str, object]]:
    path = _FIXTURE_DIR / "http_streaming_sse.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return cast(list[dict[str, object]], payload["events"])


@pytest.fixture
def app_config_regression() -> AppConfig:
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
def regression_app(app_config_regression: AppConfig) -> FastAPI:
    from src.core.app.test_builder import build_test_app

    return build_test_app(app_config_regression)


@pytest.fixture
def regression_client(regression_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(regression_app) as test_client:
        yield test_client


class TestBug1NonStreamingSessionStoreRegression:
    def test_non_streaming_http_persists_output_items_to_session_store(
        self, regression_app: FastAPI, regression_client: TestClient
    ) -> None:
        envelope = ResponseEnvelope(
            content={
                "id": "resp-ns-1",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg-ns-1",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "stored"}],
                    }
                ],
            },
            status_code=200,
        )
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            return_value=envelope,
        ):
            r = regression_client.post(
                "/v1/responses",
                json={"model": "mock-model", "input": "hello"},
            )
        assert r.status_code == 200

        store = regression_app.state.service_provider.get_required_service(
            IResponsesSessionStore
        )
        resolved = asyncio.run(store.resolve("resp-ns-1"))
        assert resolved is not None
        assert len(resolved.output_items) == 1
        assert resolved.output_items[0].id == "msg-ns-1"

    def test_non_streaming_previous_response_id_chain_does_not_404(
        self, regression_app: FastAPI, regression_client: TestClient
    ) -> None:
        first = ResponseEnvelope(
            content={
                "id": "resp-chain-a",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg-a",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "first"}],
                    }
                ],
            },
            status_code=200,
        )
        second = ResponseEnvelope(
            content={
                "id": "resp-chain-b",
                "object": "response",
                "status": "completed",
                "output": [],
            },
            status_code=200,
        )
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            side_effect=[first, second],
        ):
            regression_client.post(
                "/v1/responses",
                json={"model": "mock-model", "input": "first turn"},
            )
            out = regression_client.post(
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "input": "second turn",
                    "previous_response_id": "resp-chain-a",
                },
            )

        assert out.status_code == 200

    def test_streaming_http_sse_stores_completed_response_in_session_store(
        self, regression_app: FastAPI, regression_client: TestClient
    ) -> None:
        events = _load_sse_fixture_streaming_events()

        async def mock_stream() -> AsyncGenerator[ProcessedResponse, None]:
            for ev in events:
                yield ProcessedResponse(content=cast(dict[str, JsonValue], ev))

        with (
            patch(
                "src.core.services.request_processor_service.RequestProcessor.process_request",
                return_value=StreamingResponseEnvelope(
                    content=mock_stream(),
                    headers={"content-type": "text/event-stream"},
                    media_type="text/event-stream",
                ),
            ),
            regression_client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "input": "stream store regression",
                    "stream": True,
                },
            ) as stream_resp,
        ):
            assert stream_resp.status_code == 200
            _ = b"".join(stream_resp.iter_bytes())

        store = regression_app.state.service_provider.get_required_service(
            IResponsesSessionStore
        )
        resolved = asyncio.run(store.resolve("resp-contract-stream"))
        assert resolved is not None
        assert len(resolved.output_items) >= 1
        assert resolved.output_items[0].id == "msg_1"

    def test_non_streaming_non_dict_envelope_content_does_not_crash(
        self, regression_app: FastAPI, regression_client: TestClient
    ) -> None:
        envelope = ResponseEnvelope(content="plain-string-body")
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request",
            return_value=envelope,
        ):
            r = regression_client.post(
                "/v1/responses",
                json={"model": "mock-model", "input": "x"},
            )
        assert r.status_code == 200


@pytest.fixture
def openai_connector_for_regression():
    from unittest.mock import MagicMock

    import httpx

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_config = MagicMock()
    mock_config.streaming_yield_interval = 100
    connector = OpenAIConnector(
        client=mock_client,
        config=mock_config,
        translation_service=TranslationService(),
    )
    connector.api_key = "k"
    connector.api_base_url = "https://api.openai.com/v1"
    connector.disable_health_check()
    return connector


@pytest.fixture
def canonical_chat_request_for_regression():
    from src.connectors.contracts import ConnectorRequestContext

    return ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gpt-4",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="req-r",
            session_id="sess-r",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )


class TestBug2OpenAIConnectorNativePayloadDelegationRegression:
    @pytest.mark.asyncio
    async def test_native_projected_dict_delegates_to_responses(
        self,
        openai_connector_for_regression: OpenAIConnector,
        canonical_chat_request_for_regression: ConnectorChatCompletionsRequest,
    ) -> None:
        native = {
            "model": "gpt-4",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                }
            ],
        }
        domain = canonical_chat_request_for_regression.request.model_copy(
            update={
                "extra_body": {RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY: native},
            }
        )
        req = replace(canonical_chat_request_for_regression, request=domain)
        expected_responses_req = ConnectorResponsesRequest.from_chat_completions(req)
        with patch.object(
            openai_connector_for_regression,
            "responses",
            new_callable=AsyncMock,
        ) as mock_resp:
            mock_resp.return_value = ResponseEnvelope(
                content={"id": "r1", "object": "response"},
                status_code=200,
            )
            out = await openai_connector_for_regression.chat_completions(req)
        mock_resp.assert_awaited_once_with(expected_responses_req)
        assert out is mock_resp.return_value

    @pytest.mark.asyncio
    async def test_missing_native_key_routes_chat_completions_normally(
        self,
        openai_connector_for_regression: OpenAIConnector,
        canonical_chat_request_for_regression: ConnectorChatCompletionsRequest,
    ) -> None:
        with (
            patch.object(
                openai_connector_for_regression,
                "responses",
                new_callable=AsyncMock,
            ) as mock_resp,
            patch.object(
                openai_connector_for_regression,
                "_handle_non_streaming_response",
                new_callable=AsyncMock,
            ) as mock_handle,
        ):
            mock_handle.return_value = ResponseEnvelope(
                content={"ok": True}, status_code=200
            )
            await openai_connector_for_regression.chat_completions(
                canonical_chat_request_for_regression
            )
        mock_resp.assert_not_called()
        mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_native", [None, "not-a-dict", 123])
    async def test_non_dict_native_payload_does_not_delegate(
        self,
        openai_connector_for_regression: OpenAIConnector,
        canonical_chat_request_for_regression: ConnectorChatCompletionsRequest,
        bad_native: object,
    ) -> None:
        domain = canonical_chat_request_for_regression.request.model_copy(
            update={
                "extra_body": {RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY: bad_native},
            }
        )
        req = replace(canonical_chat_request_for_regression, request=domain)
        with (
            patch.object(
                openai_connector_for_regression,
                "responses",
                new_callable=AsyncMock,
            ) as mock_resp,
            patch.object(
                openai_connector_for_regression,
                "_handle_non_streaming_response",
                new_callable=AsyncMock,
            ) as mock_handle,
        ):
            mock_handle.return_value = ResponseEnvelope(
                content={"ok": True}, status_code=200
            )
            await openai_connector_for_regression.chat_completions(req)
        mock_resp.assert_not_called()
        mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delegation_passes_same_request_object_to_responses(
        self,
        openai_connector_for_regression: OpenAIConnector,
        canonical_chat_request_for_regression: ConnectorChatCompletionsRequest,
    ) -> None:
        native = {"model": "gpt-4", "input": []}
        domain = canonical_chat_request_for_regression.request.model_copy(
            update={
                "extra_body": {RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY: native},
            }
        )
        req = replace(canonical_chat_request_for_regression, request=domain)
        with patch.object(
            openai_connector_for_regression,
            "responses",
            new_callable=AsyncMock,
        ) as mock_resp:
            mock_resp.return_value = ResponseEnvelope(
                content={"id": "x"}, status_code=200
            )
            await openai_connector_for_regression.chat_completions(req)
        assert mock_resp.await_args is not None
        actual_req = mock_resp.await_args.args[0]
        assert isinstance(actual_req, ConnectorResponsesRequest)
        assert actual_req.request is req.request


class TestBug2ControllerNativePayloadRegression:
    def test_openai_prefixed_model_produces_native_projected_payload_for_processor(
        self, regression_client: TestClient
    ) -> None:
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            mock_process.return_value = ResponseEnvelope(
                content={
                    "id": "resp-oai",
                    "object": "response",
                    "status": "completed",
                    "output": [],
                },
                status_code=200,
            )
            regression_client.post(
                "/v1/responses",
                json={"model": "openai:gpt-4.1-mini", "input": "ping"},
            )
        forwarded = mock_process.call_args.args[1]
        native = forwarded.extra_body.get(RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY)
        assert isinstance(native, dict)
        assert native.get("model") == "openai:gpt-4.1-mini"


class TestBug3MessageShorthandNormalizerRegression:
    @pytest.mark.parametrize(
        "role",
        ["developer", "user", "assistant", "system"],
    )
    def test_role_content_shorthand_normalizes_to_message_with_input_text_part(
        self, role: str
    ) -> None:
        raw = {"model": "m", "input": [{"role": role, "content": "body"}]}
        req = ResponsesRequestNormalizer().normalize(raw)
        assert len(req.input) == 1
        assert req.input[0].type == "message"
        assert req.input[0].role == role
        assert req.input[0].content is not None
        parts = req.input[0].content
        assert isinstance(parts, list)
        assert parts[0].type == "input_text"
        assert parts[0].text == "body"

    def test_list_content_preserved_for_shorthand(self) -> None:
        raw = {
            "model": "m",
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                }
            ],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        parts = req.input[0].content
        assert isinstance(parts, list)
        assert parts[0].type == "input_text"
        assert parts[0].text == "hi"

    def test_explicit_type_not_rewritten(self) -> None:
        raw = {
            "model": "m",
            "input": [
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": "{}",
                }
            ],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert req.input[0].type == "function_call_output"

    def test_without_role_not_shorthand(self) -> None:
        raw = {"model": "m", "input": [{"content": "only"}]}
        with pytest.raises(ResponsesValidationError):
            ResponsesRequestNormalizer().normalize(raw)

    def test_without_content_not_shorthand(self) -> None:
        raw = {"model": "m", "input": [{"role": "user"}]}
        with pytest.raises(ResponsesValidationError):
            ResponsesRequestNormalizer().normalize(raw)

    def test_empty_role_string_not_shorthand(self) -> None:
        raw = {"model": "m", "input": [{"role": "  ", "content": "x"}]}
        with pytest.raises(ResponsesValidationError):
            ResponsesRequestNormalizer().normalize(raw)

    def test_shorthand_with_extra_fields_like_id(self) -> None:
        raw = {
            "model": "m",
            "input": [{"id": "local-1", "role": "user", "content": "hi"}],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert req.input[0].type == "message"
        assert req.input[0].id == "local-1"

    def test_mixed_typed_and_shorthand_items(self) -> None:
        raw = {
            "model": "m",
            "input": [
                {"type": "function_call_output", "call_id": "c", "output": "{}"},
                {"role": "user", "content": "next"},
            ],
        }
        req = ResponsesRequestNormalizer().normalize(raw)
        assert req.input[0].type == "function_call_output"
        assert req.input[1].type == "message"
        assert req.input[1].role == "user"

    def test_shorthand_does_not_mutate_source_dict(self) -> None:
        entry: dict[str, Any] = {"role": "user", "content": "z"}
        raw = {"model": "m", "input": [entry]}
        ResponsesRequestNormalizer().normalize(raw)
        assert "type" not in entry
        assert entry["role"] == "user"
        assert entry["content"] == "z"
