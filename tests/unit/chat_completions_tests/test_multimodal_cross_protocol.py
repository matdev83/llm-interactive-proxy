from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app


@pytest.fixture
def app():
    cfg = {
        "disable_auth": True,
        "interactive_mode": False,
        "command_prefix": "!/",
        "proxy_timeout": 10,
        "openrouter_api_keys": {"k": "v"},
        "gemini_api_keys": {"k": "v"},
    }
    return build_app(cfg)


@pytest.fixture
def client(app):
    return TestClient(app)


def test_openai_frontend_to_gemini_backend_multimodal(client):
    # Route to Gemini backend explicitly
    client.app.state.backend_type = "gemini"

    # Ensure backend exists on app state and patch its chat_completions
    if (
        not hasattr(client.app.state, "gemini_backend")
        or client.app.state.gemini_backend is None
    ):

        class _GB:  # minimal stub
            async def chat_completions(self, *args, **kwargs):
                return {
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "gemini:gemini-pro",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }

        client.app.state.gemini_backend = _GB()

    with patch.object(
        client.app.state.gemini_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_gemini:
        mock_gemini.return_value = {
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "gemini:gemini-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        payload = {
            "model": "gemini:gemini-pro",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "http://example.com/img.jpg"},
                        },
                    ],
                }
            ],
        }
        r = client.post("/v1/chat/completions", json=payload)
        assert r.status_code == 200
        assert mock_gemini.await_count == 1
        # Verify processed_messages preserved multimodal list
        kwargs = mock_gemini.call_args.kwargs
        processed = kwargs.get("processed_messages")
        assert processed and isinstance(processed[0].content, list)
        assert processed[0].content[0].type == "text"
        assert processed[0].content[1].type == "image_url"


def test_gemini_frontend_to_openai_backend_multimodal(client):
    # Ensure openrouter backend exists on state and patch it directly
    if (
        not hasattr(client.app.state, "openrouter_backend")
        or client.app.state.openrouter_backend is None
    ):

        class _OR:
            async def chat_completions(self, *args, **kwargs):
                return {
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ]
                }, {}

        client.app.state.openrouter_backend = _OR()

    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_or:
        mock_or.return_value = (
            {
                "id": "y",
                "object": "chat.completion",
                "created": 0,
                "model": "openrouter:gpt-4",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
            {},
        )

        gemini_request = {
            "contents": [
                {
                    "parts": [
                        {"text": "What is in this image?"},
                        {"inline_data": {"mime_type": "image/png", "data": "aGVsbG8="}},
                    ],
                    "role": "user",
                }
            ]
        }
        r = client.post(
            "/v1beta/models/openrouter:gpt-4:generateContent", json=gemini_request
        )
        assert r.status_code == 200
        assert mock_or.await_count == 1
        # Verify OpenAI-shaped request had expected text placeholder
        kwargs = mock_or.call_args.kwargs
        openai_req = kwargs.get("request_data")
        assert openai_req is not None
        assert isinstance(openai_req.messages[0].content, str)
        assert openai_req.messages[0].content.endswith("[Attachment: image/png]")
