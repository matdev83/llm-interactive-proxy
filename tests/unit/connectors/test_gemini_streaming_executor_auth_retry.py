from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests  # type: ignore[import-untyped]
from requests.structures import CaseInsensitiveDict  # type: ignore[import-untyped]
from src.connectors.gemini_base.chat_request_preparer import PreparedChatRequest
from src.connectors.gemini_base.streaming_executor import StreamingExecutor


class _CredentialStub:
    def __init__(self, token: str) -> None:
        self.token = token
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def before_request(
        self,
        request: Any,
        method: str,
        url: str,
        headers: dict[str, str],
    ) -> None:
        del request
        self.calls.append((method, url, dict(headers)))
        headers["Authorization"] = f"Bearer {self.token}"

    def refresh(self, request: Any) -> None:
        del request


class _AuthorizedSessionDouble:
    def __init__(self, responses: list[requests.Response], token: str = "OLD") -> None:
        self.credentials = _CredentialStub(token)
        self._auth_request = object()
        self.headers = {"User-Agent": "antigravity/1.11.5 windows/amd64"}
        self._responses = list(responses)
        self._session = requests.Session()
        self.sent_requests: list[requests.PreparedRequest] = []

    def prepare_request(self, request: requests.Request) -> requests.PreparedRequest:
        self._session.headers.clear()
        self._session.headers.update(self.headers)
        return self._session.prepare_request(request)

    def merge_environment_settings(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {}

    def send(
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        del kwargs
        self.sent_requests.append(request)
        response = self._responses.pop(0)
        response.request = request
        return response


def _build_401_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 401
    response.reason = "Unauthorized"
    response.headers = CaseInsensitiveDict({"content-type": "application/json"})
    response._content = (
        b'{"error":{"code":401,"message":"Request is missing required '
        b'authentication credential.","status":"UNAUTHENTICATED"}}'
    )
    return response


def _build_streaming_response() -> requests.Response:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.reason = "OK"
    response.headers = CaseInsensitiveDict({"content-type": "text/event-stream"})
    response._content = False
    response.close = MagicMock()

    def iter_content(
        chunk_size: int = 4096, decode_unicode: bool = False
    ) -> Iterator[bytes]:
        del chunk_size, decode_unicode
        yield (
            b'data: {"candidates":[{"content":{"parts":[{"text":"hello"}]},'
            b'"finishReason":"STOP"}]}'
            b"\n\n"
        )

    response.iter_content = iter_content
    return response


@pytest.mark.asyncio
async def test_streaming_executor_applies_auth_to_send_retry_after_refresh() -> None:
    translation_service = MagicMock()
    translation_service.to_domain_stream_chunk.side_effect = lambda **kwargs: {
        "id": "chatcmpl-auth-retry",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "content": kwargs["chunk"]["candidates"][0]["content"]["parts"][0][
                        "text"
                    ]
                },
                "finish_reason": "stop",
            }
        ],
    }

    auth_session = _AuthorizedSessionDouble(
        [_build_401_response(), _build_streaming_response()],
        token="OLD",
    )
    prepared = PreparedChatRequest(
        auth_session=auth_session,
        project_id="project-antigravity",
        canonical_request=None,
        code_assist_request={
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}]
        },
        prompt_tokens_estimate=0,
        effective_model="google/gemini-3-flash-preview",
        session_id="sess-auth-retry",
        signature_session_id="sess-auth-retry",
        build_request_body=lambda: {
            "requestId": "req-auth-retry",
            "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
        },
    )

    token_refresher = MagicMock()
    token_refresher.backend_type = "gemini-oauth-auto"
    token_refresher._oauth_credentials = {"access_token": "OLD"}

    async def _refresh_token_if_needed(**kwargs: Any) -> bool:
        del kwargs
        token_refresher._oauth_credentials = {"access_token": "NEW"}
        return True

    token_refresher.refresh_token_if_needed = AsyncMock(
        side_effect=_refresh_token_if_needed
    )

    executor = StreamingExecutor(
        translation_service=translation_service,
        backend_type="gemini-oauth-auto",
    )

    chunks = [
        chunk
        async for chunk in executor.execute(
            prepared,
            "https://example.invalid/v1internal:streamGenerateContent",
            token_refresher=token_refresher,
        )
    ]

    assert chunks
    assert auth_session.sent_requests[0].headers["Authorization"] == "Bearer OLD"
    assert auth_session.sent_requests[1].headers["Authorization"] == "Bearer NEW"
    assert auth_session.credentials.token == "NEW"
    token_refresher.refresh_token_if_needed.assert_awaited_once()
    assert len(auth_session.credentials.calls) >= 2
