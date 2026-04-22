"""Regression coverage for Responses API routing compatibility."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from src.core.app.controllers.responses_controller import ResponsesController
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.responses_api import ResponsesRequest
from src.core.domain.responses_event_normalizer import ResponsesStreamSource
from src.core.domain.responses_native_wiring import (
    RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY,
)

from tests.utils.responses_controller_test_deps import (
    build_responses_controller_backend_kwargs,
)


class _StubTranslationService:
    def __init__(self) -> None:
        self._domain_request = CanonicalChatRequest(
            model="gpt-test",
            messages=[ChatMessage(role="user", content="stub")],
            stream=False,
        )

    def to_domain_request(
        self, request: object, source_format: str
    ) -> CanonicalChatRequest:
        return self._domain_request

    def from_domain_request(
        self, request: CanonicalChatRequest, target_format: str
    ) -> dict[str, object]:
        return {"model": request.model, "target_format": target_format}

    def to_domain_response(self, response: object, source_format: str) -> object:
        return response


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/responses",
        "headers": [],
        "client": ("127.0.0.1", 12345),
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive=receive)
    request.state.request_id = "req-regression-responses-routing"
    return request


def _responses_request(**kwargs: object) -> ResponsesRequest:
    payload: dict[str, object] = {"model": "alias:minimax", "input": "hello"}
    payload.update(kwargs)
    return ResponsesRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_prepare_responses_execution_accepts_legacy_openai_style_backend_targets() -> None:
    """Responses routing should treat OpenAI-compatible backends like `opencode-go` as supported.

    Regression evidence: the 2026-04-20 10:34:13 log/capture shows `/v1/responses`
    requests for `alias:minimax` failing after the first composite leaf resolves to `ollama`,
    even though later leaves include OpenAI-compatible backends (`opencode-go`, `opencode-zen`).
    """

    kwargs = build_responses_controller_backend_kwargs()
    kwargs["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="opencode-go",
            model="minimax-m2.7",
            uri_params={},
        )
    )

    controller = ResponsesController(
        AsyncMock(),
        translation_service=_StubTranslationService(),
        **kwargs,
    )

    _, canonical, stream_source, _ = await controller._prepare_responses_execution(
        responses_request=_responses_request(),
    )

    assert stream_source is ResponsesStreamSource.OPENAI_RESPONSES
    assert canonical.model == "opencode-go:minimax-m2.7"
    assert canonical.extra_body is not None
    assert RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY in canonical.extra_body


@pytest.mark.asyncio
async def test_handle_responses_request_succeeds_for_alias_that_can_fall_through_to_legacy_openai_backend() -> None:
    """Composite aliases used from `/v1/responses` should remain usable when a later leaf is compatible.

    This is the user-visible regression from the 2026-04-20 10:34:13 failure: the
    client asked for `alias:minimax`, whose configured replacement includes
    `opencode-go:minimax-m2.7`, but the request died with `responses_api.routing`
    before a Responses-compatible branch could be used.
    """

    kwargs = build_responses_controller_backend_kwargs()
    kwargs["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="opencode-go",
            model="minimax-m2.7",
            uri_params={},
        )
    )

    processor = AsyncMock()
    processor.process_request.return_value = ResponseEnvelope(
        content={
            "id": "resp-minimax-ok",
            "object": "response",
            "output": [],
        }
    )

    controller = ResponsesController(
        processor,
        translation_service=_StubTranslationService(),
        **kwargs,
    )

    response = await controller.handle_responses_request(
        _make_request(),
        _responses_request(model="alias:minimax", input="hello"),
    )

    assert response.status_code == 200
    processor.process_request.assert_awaited_once()
    domain_request = cast(CanonicalChatRequest, processor.process_request.await_args.args[1])
    assert domain_request.model == "opencode-go:minimax-m2.7"
    assert domain_request.extra_body is not None
    assert RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY in domain_request.extra_body
