from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from src.core.app.controllers import (
    get_anthropic_controller_if_available,
    get_chat_controller_if_available,
)
from src.core.app.test_builder import build_test_app
from src.core.common.exceptions import RoutingError
from src.core.domain.responses import ResponseEnvelope


class _FailingChatController:
    async def handle_chat_completion(self, request, request_data):  # type: ignore[no-untyped-def]
        raise RoutingError(
            message="Unknown model across protocols",
            details={
                "code": "unknown_model",
                "category": "validation",
                "retryable": False,
            },
        )


class _FailingAnthropicController:
    async def handle_anthropic_messages(self, request, request_data):  # type: ignore[no-untyped-def]
        raise RoutingError(
            message="Unknown model across protocols",
            details={
                "code": "unknown_model",
                "category": "validation",
                "retryable": False,
            },
        )


def _unknown_model_routing_error() -> RoutingError:
    return RoutingError(
        message="Unknown model across protocols",
        details={
            "code": "unknown_model",
            "category": "validation",
            "retryable": False,
        },
    )


def _extract_error_code(payload: dict[str, object]) -> str | None:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        nested_detail = detail.get("details")
        if isinstance(nested_detail, dict):
            code = nested_detail.get("code")
            if isinstance(code, str):
                return code
    details = payload.get("details")
    if isinstance(details, dict):
        code = details.get("code")
        if isinstance(code, str):
            return code
    error = payload.get("error")
    if isinstance(error, dict):
        nested = error.get("details")
        if isinstance(nested, dict):
            code = nested.get("code")
            if isinstance(code, str):
                return code
    return None


def test_openai_and_anthropic_surfaces_preserve_routing_error_semantics(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    app.dependency_overrides[get_chat_controller_if_available] = (
        lambda: _FailingChatController()
    )
    app.dependency_overrides[get_anthropic_controller_if_available] = (
        lambda: _FailingAnthropicController()
    )

    with TestClient(app) as client:
        openai_response = client.post(
            "/v1/chat/completions",
            json={
                "model": "openai/gpt-4o",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        anthropic_response = client.post(
            "/anthropic/v1/messages",
            json={
                "model": "anthropic/claude-3-5-sonnet",
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert openai_response.status_code == 404
    assert anthropic_response.status_code == 404
    assert openai_response.json()["details"]["code"] == "unknown_model"
    assert anthropic_response.json()["details"]["code"] == "unknown_model"


def test_openai_anthropic_and_gemini_map_unknown_model_consistently(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()

    with patch(
        "src.core.services.backend_service.BackendService.call_completion",
        new_callable=AsyncMock,
    ) as mock_call_completion:
        mock_call_completion.side_effect = _unknown_model_routing_error()

        with TestClient(app) as client:
            openai_response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "openai/gpt-4o",
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            anthropic_response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "anthropic/claude-3-5-sonnet",
                    "max_tokens": 16,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            gemini_response = client.post(
                "/v1beta/models/test-model:generateContent",
                json={
                    "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
                },
            )

    assert openai_response.status_code == 404
    assert anthropic_response.status_code == 404
    assert gemini_response.status_code == 404
    assert _extract_error_code(openai_response.json()) == "unknown_model"
    assert _extract_error_code(anthropic_response.json()) == "unknown_model"
    assert _extract_error_code(gemini_response.json()) == "unknown_model"


def test_uri_model_selector_is_forwarded_consistently_across_protocol_surfaces(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_test_app()
    model_selector = "openai/gpt-4o?temperature=0.35&top_p=0.8"
    observed_models: list[str] = []

    async def _record_call(*args, **kwargs):
        request = kwargs.get("request")
        if request is None and args:
            request = args[0]
        observed_models.append(str(getattr(request, "model", "")))
        return ResponseEnvelope(
            content={
                "id": "chatcmpl-protocol-parity",
                "object": "chat.completion",
                "created": 0,
                "model": "openai/gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
            status_code=200,
            headers={},
        )

    with (
        patch(
            "src.core.services.backend_service.BackendService.call_completion",
            new=_record_call,
        ),
        TestClient(app) as client,
    ):
        openai_response = client.post(
            "/v1/chat/completions",
            json={
                "model": model_selector,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        anthropic_response = client.post(
            "/anthropic/v1/messages",
            json={
                "model": model_selector,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        gemini_response = client.post(
            "/v1beta/models/test-model:generateContent",
            json={
                "model": model_selector,
                "contents": [{"role": "user", "parts": [{"text": "hi"}]}],
            },
        )

    assert openai_response.status_code == 200
    assert anthropic_response.status_code == 200
    assert gemini_response.status_code == 200
    assert observed_models[:3] == [model_selector, model_selector, model_selector]
