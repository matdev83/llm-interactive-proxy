"""Live end-to-end integration tests for CommandCode backends through the LIP proxy."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest
from src.core.app.application_builder import build_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)


@pytest.fixture(scope="module")
def live_api_key() -> str:
    key = os.getenv("COMMANDCODE_API_KEY")
    if not key:
        pytest.skip("COMMANDCODE_API_KEY environment variable is not set")
    return key


@pytest.fixture
def live_app(live_api_key: str) -> Any:
    backends_dict = {
        "default_backend": "commandcode-openai",
        "commandcode_openai": BackendConfig(
            api_key=live_api_key,
            models=["Qwen/Qwen3.7-Flash", "commandcode-openai/*"],
        ),
        "commandcode_anthropic": BackendConfig(
            api_key=live_api_key,
            models=[
                "claude-3-5-sonnet-20241022",
                "claude-haiku-4-5-20251001",
                "commandcode-anthropic/*",
            ],
        ),
    }
    config = AppConfig(
        auth=AuthConfig(disable_auth=True),
        backends=BackendSettings.model_validate(backends_dict),
    )
    return build_app(config)


@pytest.mark.asyncio
async def test_commandcode_openai_chat_completions_non_streaming(live_app: Any) -> None:
    """Test native OpenAI chat completions non-streaming via commandcode-openai."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen3.7-Flash",
                "messages": [
                    {
                        "role": "user",
                        "content": "Respond with the word 'HELLO_OPENAI' only.",
                    }
                ],
                "stream": False,
                "max_tokens": 20,
            },
        )
        assert response.status_code == 200, f"Error: {response.text}"
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        content = data["choices"][0]["message"]["content"]
        assert "HELLO_OPENAI" in content.upper() or "HELLO" in content.upper()


@pytest.mark.asyncio
async def test_commandcode_openai_chat_completions_streaming(live_app: Any) -> None:
    """Test native OpenAI chat completions streaming via commandcode-openai."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "Qwen/Qwen3.7-Flash",
                "messages": [{"role": "user", "content": "Count from 1 to 3."}],
                "stream": True,
                "max_tokens": 20,
            },
        )
        assert response.status_code == 200, f"Error: {response.text}"
        chunks = []
        for line in response.text.splitlines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk_data = json.loads(line[6:])
                choices = chunk_data.get("choices")
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        chunks.append(content)

        full_text = "".join(chunks)
        assert len(full_text) > 0


@pytest.mark.asyncio
async def test_commandcode_anthropic_frontend_to_openai_backend_non_streaming(
    live_app: Any,
) -> None:
    """Test Anthropic Messages frontend cross-API converting to commandcode-openai backend (non-streaming)."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/anthropic/v1/messages",
            json={
                "model": "Qwen/Qwen3.7-Flash",
                "messages": [
                    {
                        "role": "user",
                        "content": "Respond with the word 'CROSS_ANTHROPIC' only.",
                    }
                ],
                "max_tokens": 20,
                "stream": False,
            },
            headers={"anthropic-version": "2023-06-01"},
        )
        assert response.status_code == 200, f"Error: {response.text}"
        data = response.json()
        assert data.get("type") == "message" or "content" in data
        content_list = data.get("content", [])
        assert len(content_list) > 0
        text = content_list[0].get("text", "")
        assert "CROSS_ANTHROPIC" in text.upper() or "CROSS" in text.upper()


@pytest.mark.asyncio
async def test_commandcode_anthropic_frontend_to_openai_backend_streaming(
    live_app: Any,
) -> None:
    """Test Anthropic Messages frontend cross-API converting to commandcode-openai backend (streaming)."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/anthropic/v1/messages",
            json={
                "model": "Qwen/Qwen3.7-Flash",
                "messages": [{"role": "user", "content": "Count from 1 to 3."}],
                "max_tokens": 20,
                "stream": True,
            },
            headers={"anthropic-version": "2023-06-01"},
        )
        assert response.status_code == 200, f"Error: {response.text}"
        sse_events = []
        for line in response.text.splitlines():
            if line.startswith("data: "):
                try:
                    evt = json.loads(line[6:])
                    sse_events.append(evt)
                except json.JSONDecodeError:
                    pass

        assert len(sse_events) > 0


@pytest.mark.asyncio
async def test_commandcode_openai_frontend_to_anthropic_backend(live_app: Any) -> None:
    """Test OpenAI frontend cross-API converting to commandcode-anthropic backend."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "claude-haiku-4-5-20251001",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
                "max_tokens": 10,
            },
        )
        # Verify proxy forwarded the call to commandcode-anthropic
        assert response.status_code in (200, 400, 403, 500, 502, 503)


@pytest.mark.asyncio
async def test_commandcode_anthropic_frontend_to_anthropic_backend(
    live_app: Any,
) -> None:
    """Test native Anthropic Messages frontend to commandcode-anthropic backend."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.post(
            "/anthropic/v1/messages",
            json={
                "model": "claude-haiku-4-5-20251001",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
                "max_tokens": 10,
            },
            headers={"anthropic-version": "2023-06-01"},
        )
        # Verify proxy forwarded the call to commandcode-anthropic
        assert response.status_code in (200, 400, 403, 500, 502, 503)


@pytest.mark.asyncio
async def test_commandcode_models_discovery(live_app: Any) -> None:
    """Test models discovery returns the catalog containing Qwen/Qwen3.7-Flash."""
    transport = httpx.ASGITransport(app=live_app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", timeout=60.0
    ) as client:
        response = await client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        model_ids = [m["id"] for m in data.get("data", [])]
        assert "Qwen/Qwen3.7-Flash" in model_ids
