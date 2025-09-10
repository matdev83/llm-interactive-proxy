from __future__ import annotations

from types import SimpleNamespace

from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)


class _DummyRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.cookies = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace(request_state={})
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.method = "POST"
        self.url = "http://localhost/test"


def test_request_context_agent_from_x_agent_header() -> None:
    req = _DummyRequest({"X-Agent": "cline", "User-Agent": "ua-default"})
    ctx = fastapi_to_domain_request_context(req, attach_original=True)  # type: ignore[arg-type]
    assert ctx.client_host == "127.0.0.1"
    assert ctx.agent == "cline"


def test_request_context_agent_from_x_client_agent_header() -> None:
    req = _DummyRequest({"X-Client-Agent": "my-agent", "User-Agent": "ua-default"})
    ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
    assert ctx.agent == "my-agent"


def test_request_context_agent_falls_back_to_user_agent_truncated() -> None:
    long_ua = "x" * 200
    req = _DummyRequest({"User-Agent": long_ua})
    ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
    assert ctx.agent is not None
    assert len(ctx.agent) == 80
    assert ctx.agent == long_ua[:80]
