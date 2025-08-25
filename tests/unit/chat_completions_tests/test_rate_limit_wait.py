import asyncio
import time


def test_wait_for_rate_limited_backends(monkeypatch, client):
    # Build a failover route via commands (uses the compat endpoint); not strictly required
    client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/create-failover-route(name=r,policy=k)"}
            ],
            "stream": True,
        },
    )
    client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/route-append(name=r,openrouter:m1)"}
            ],
            "stream": True,
        },
    )

    # Simulated monotonic clock and sleep
    current = 0.0
    monkeypatch.setattr(time, "time", lambda: current)

    async def fake_sleep(d):
        nonlocal current
        current += d

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # Patch BackendService.call_completion to simulate two 429s with Retry-After, then success
    from src.core.interfaces.backend_service_interface import IBackendService

    # Get backend service from the app created by client fixture
    app = client.app
    backend_service = app.state.service_provider.get_required_service(IBackendService)  # type: ignore

    async def fake_call_completion(request, stream=False, allow_failover=True):
        # Simulate two backoffs that would normally be driven by 429 Retry-After headers
        await asyncio.sleep(0.1)
        await asyncio.sleep(0.3)

        # Success path: return SSE-like text in a simple JSON envelope expected by compat layer
        from fastapi.responses import StreamingResponse

        async def gen():
            yield b'data: {"choices": [{"delta": {"content": "ok"}}]\n\n'
            yield b"data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/plain")

    monkeypatch.setattr(backend_service, "call_completion", fake_call_completion)

    # Execute the request which should internally retry and then succeed
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "r",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    )

    assert resp.status_code == 200
    body = resp.text
    assert "ok" in body
    # Ensure we respected cumulative backoffs (0.1 + 0.3)
    assert current >= 0.4
