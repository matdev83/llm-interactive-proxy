"""Tests for InternLM connector."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.base import LLMBackend
from src.connectors.internlm import InternLMConnector
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock()


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return MagicMock(spec=AppConfig)


@pytest.fixture
def mock_translation_service():
    """Create a mock translation service."""
    return MagicMock()


@pytest.fixture
async def internlm_backend(mock_client, mock_config, mock_translation_service):
    """Create an InternLMConnector instance."""
    mock_translation_service.from_domain_request.side_effect = (
        lambda request, *_args, **_kwargs: {
            "model": getattr(request, "model", None),
            "messages": getattr(request, "messages", []),
            "stream": getattr(request, "stream", False),
        }
    )
    backend = InternLMConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )
    await backend.initialize(api_key="test-key")
    return backend


class TestInternLMConnector:
    """Test class for InternLMConnector."""

    async def test_backend_type(self, internlm_backend: InternLMConnector):
        """Test that backend type is set correctly."""
        assert internlm_backend.backend_type == "internlm"

    async def test_api_base_url(self, internlm_backend: InternLMConnector):
        """Test that API base URL is set correctly."""
        assert internlm_backend.api_base_url == "https://chat.intern-ai.org.cn/api/v1"

    async def test_backend_initialization(self, internlm_backend: InternLMConnector):
        """Test backend initialization with API key."""
        assert internlm_backend.api_key == "test-key"
        assert internlm_backend.api_keys == ["test-key"]

    async def test_get_headers(self, internlm_backend: InternLMConnector):
        """Test that headers include Authorization with Bearer token."""
        headers = internlm_backend.get_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-key"

    async def test_name_property(self, internlm_backend: InternLMConnector):
        """Test that name property is set correctly."""
        assert internlm_backend.name == "internlm"

    async def test_inherits_from_llm_backend(self):
        """Test that InternLMConnector inherits from LLMBackend."""
        assert issubclass(InternLMConnector, LLMBackend)

    async def test_get_available_models(self, internlm_backend: InternLMConnector):
        """Test that get_available_models returns vendor-prefixed models."""
        models = internlm_backend.get_available_models()
        assert len(models) == 4
        # All models should have vendor prefix
        assert all(model.startswith("internlm/") for model in models)
        # Check expected models
        assert "internlm/intern-latest" in models
        assert "internlm/intern-s1-pro" in models
        assert "internlm/intern-s1" in models
        assert "internlm/intern-s1-mini" in models


class TestInternLMConnectorInitialization:
    """Test InternLMConnector initialization scenarios."""

    async def test_initialize_with_api_key(self, mock_client, mock_config):
        """Test initialization with single API key."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(api_key="test-api-key")
        assert backend.api_key == "test-api-key"
        assert backend.api_keys == ["test-api-key"]

    async def test_initialize_with_multiple_api_keys(self, mock_client, mock_config):
        """Test initialization with multiple API keys."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(
            api_key="primary-key", api_keys=["primary-key", "key-1", "key-2"]
        )
        assert backend.api_key == "primary-key"
        assert len(backend.api_keys) == 3
        assert "primary-key" in backend.api_keys
        assert "key-1" in backend.api_keys
        assert "key-2" in backend.api_keys

    async def test_initialize_with_api_keys_list_only(self, mock_client, mock_config):
        """Test initialization with api_keys list but no primary api_key."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(api_keys=["key-1", "key-2"])
        assert backend.api_key == "key-1"
        assert backend.api_keys == ["key-1", "key-2"]

    async def test_initialize_with_custom_api_base_url(self, mock_client, mock_config):
        """Test initialization with custom API base URL."""
        backend = InternLMConnector(mock_client, mock_config)
        custom_url = "https://custom.internlm.ai/api/v1"
        await backend.initialize(api_key="test-key", api_base_url=custom_url)
        assert backend.api_base_url == custom_url

    async def test_default_api_base_url(self, mock_client, mock_config):
        """Test that default API base URL is set correctly."""
        backend = InternLMConnector(mock_client, mock_config)
        assert backend.api_base_url == "https://chat.intern-ai.org.cn/api/v1"


class TestInternLMConnectorKeyRotation:
    """Test API key rotation functionality."""

    async def test_key_rotation_round_robin(self, mock_client, mock_config):
        """Test that keys are rotated round-robin."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(api_keys=["key-1", "key-2", "key-3"])

        # First call should use key-1
        headers1 = backend.get_headers()
        assert headers1["Authorization"] == "Bearer key-1"

        # Second call should use key-2
        headers2 = backend.get_headers()
        assert headers2["Authorization"] == "Bearer key-2"

        # Third call should use key-3
        headers3 = backend.get_headers()
        assert headers3["Authorization"] == "Bearer key-3"

        # Fourth call should wrap around to key-1
        headers4 = backend.get_headers()
        assert headers4["Authorization"] == "Bearer key-1"

    async def test_single_key_no_rotation(self, mock_client, mock_config):
        """Test that single key doesn't rotate."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(api_key="single-key")

        # Multiple calls should use the same key
        headers1 = backend.get_headers()
        headers2 = backend.get_headers()
        headers3 = backend.get_headers()

        assert headers1["Authorization"] == "Bearer single-key"
        assert headers2["Authorization"] == "Bearer single-key"
        assert headers3["Authorization"] == "Bearer single-key"

    async def test_rotate_to_next_key(self, mock_client, mock_config):
        """Test manual key rotation."""
        backend = InternLMConnector(mock_client, mock_config)
        await backend.initialize(api_keys=["key-1", "key-2"])

        # Start with key-1 (get_headers advances index to 1)
        headers1 = backend.get_headers()
        assert headers1["Authorization"] == "Bearer key-1"
        # Index is now 1

        # Next call uses key-2 and advances index to 0 (wraps)
        headers2 = backend.get_headers()
        assert headers2["Authorization"] == "Bearer key-2"
        # Index is now 0

        # Manually rotate advances index to 1
        backend._rotate_to_next_key()
        # Index is now 1, so next call uses key-2
        headers3 = backend.get_headers()
        assert headers3["Authorization"] == "Bearer key-2"


class TestInternLMPreparePayload:
    """Test that _prepare_payload always forces stream=False."""

    async def test_payload_forces_stream_false(
        self, internlm_backend: InternLMConnector
    ):
        """Payload must always contain stream=False regardless of request."""
        request_data = MagicMock()
        request_data.stream = True
        request_data.model = "internlm/intern-s1-pro"

        payload = await internlm_backend._prepare_payload(
            request_data, [], "internlm/intern-s1-pro"
        )
        assert payload["stream"] is False

    async def test_payload_stream_false_when_client_not_streaming(
        self, internlm_backend: InternLMConnector
    ):
        """Payload has stream=False even when client explicitly requests non-streaming."""
        request_data = MagicMock()
        request_data.stream = False
        request_data.model = "internlm/intern-s1"

        payload = await internlm_backend._prepare_payload(
            request_data, [], "internlm/intern-s1"
        )
        assert payload["stream"] is False

    async def test_payload_enables_thinking_mode(
        self, internlm_backend: InternLMConnector
    ):
        """Payload must include thinking_mode=True for InternLM."""
        request_data = MagicMock()
        request_data.stream = False
        request_data.model = "internlm/intern-s1-pro"

        payload = await internlm_backend._prepare_payload(
            request_data, [], "internlm/intern-s1-pro"
        )
        assert payload["thinking_mode"] is True

    async def test_payload_strips_vendor_prefix(
        self, internlm_backend: InternLMConnector
    ):
        """Model name in payload should have vendor prefix stripped."""
        request_data = MagicMock()
        request_data.stream = False
        request_data.model = "internlm/intern-s1-pro"

        payload = await internlm_backend._prepare_payload(
            request_data, [], "internlm/intern-s1-pro"
        )
        assert payload["model"] == "intern-s1-pro"


class TestInternLMToStreamingChunk:
    """Test the _to_streaming_chunk static method."""

    def test_converts_object_type(self):
        """Object type changes from chat.completion to chat.completion.chunk."""
        response = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "intern-s1-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        }
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert chunk["object"] == "chat.completion.chunk"

    def test_renames_message_to_delta(self):
        """Each choice's 'message' key is renamed to 'delta'."""
        response = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "intern-s1-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
        }
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert "delta" in chunk["choices"][0]
        assert "message" not in chunk["choices"][0]
        assert chunk["choices"][0]["delta"]["content"] == "Hello!"
        assert chunk["choices"][0]["delta"]["role"] == "assistant"

    def test_preserves_finish_reason(self):
        """finish_reason is preserved in the streaming chunk."""
        response = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "intern-s1-pro",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                }
            ],
        }
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert chunk["choices"][0]["finish_reason"] == "stop"

    def test_preserves_id_and_created(self):
        """Original id and created are preserved."""
        response = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "intern-s1-pro",
            "choices": [],
        }
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert chunk["id"] == "chatcmpl-abc"
        assert chunk["created"] == 1700000000

    def test_injects_fallback_id_when_absent(self):
        """A fallback id is generated when the response has no id."""
        response = {"object": "chat.completion", "choices": []}
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert chunk["id"].startswith("chatcmpl-internlm-")

    def test_injects_fallback_created_when_absent(self):
        """A fallback created timestamp is generated when absent."""
        response = {"object": "chat.completion", "choices": []}
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert isinstance(chunk["created"], int)
        assert chunk["created"] > 0

    def test_does_not_mutate_original(self):
        """The original dict is not mutated."""
        response = {
            "id": "chatcmpl-abc",
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "OK"}}
            ],
        }
        InternLMConnector._to_streaming_chunk(response)
        # Original must still have "message", not "delta"
        assert "message" in response["choices"][0]

    def test_handles_multiple_choices(self):
        """Multiple choices are all converted."""
        response = {
            "object": "chat.completion",
            "choices": [
                {"index": 0, "message": {"content": "A"}},
                {"index": 1, "message": {"content": "B"}},
            ],
        }
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert len(chunk["choices"]) == 2
        assert chunk["choices"][0]["delta"]["content"] == "A"
        assert chunk["choices"][1]["delta"]["content"] == "B"

    def test_handles_empty_choices(self):
        """Empty choices list is handled gracefully."""
        response = {"object": "chat.completion", "choices": []}
        chunk = InternLMConnector._to_streaming_chunk(response)
        assert chunk["choices"] == []


class TestInternLMWrapAsStreamingEnvelope:
    """Test the _wrap_as_streaming_envelope method."""

    async def test_returns_streaming_envelope(
        self, internlm_backend: InternLMConnector
    ):
        """Wrapping produces a StreamingResponseEnvelope."""
        response = ResponseEnvelope(
            content={
                "id": "chatcmpl-abc",
                "object": "chat.completion",
                "model": "intern-s1-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello!"},
                        "finish_reason": "stop",
                    }
                ],
            },
            status_code=200,
            headers={"x-custom": "value"},
        )
        result = internlm_backend._wrap_as_streaming_envelope(response)
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"
        assert result.status_code == 200
        assert result.headers == {"x-custom": "value"}

    async def test_synthetic_stream_yields_content_and_done(
        self, internlm_backend: InternLMConnector
    ):
        """The synthetic SSE stream yields exactly one content chunk then [DONE]."""
        response = ResponseEnvelope(
            content={
                "id": "chatcmpl-abc",
                "object": "chat.completion",
                "model": "intern-s1-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello!"},
                        "finish_reason": "stop",
                    }
                ],
            },
            status_code=200,
        )
        envelope = internlm_backend._wrap_as_streaming_envelope(response)
        assert envelope.content is not None

        chunks: list[ProcessedResponse] = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        assert len(chunks) == 2

        # First chunk: SSE-formatted content
        first_content = chunks[0].content
        assert isinstance(first_content, bytes)
        assert first_content.startswith(b"data: ")
        assert first_content.endswith(b"\n\n")

        # Parse the JSON from the SSE event
        json_str = first_content[len(b"data: ") : -len(b"\n\n")]
        parsed = json.loads(json_str)
        assert parsed["object"] == "chat.completion.chunk"
        assert parsed["choices"][0]["delta"]["content"] == "Hello!"

        # Second chunk: [DONE] sentinel
        second_content = chunks[1].content
        assert isinstance(second_content, bytes)
        assert second_content == b"data: [DONE]\n\n"

    async def test_synthetic_stream_with_empty_content(
        self, internlm_backend: InternLMConnector
    ):
        """Wrapping a non-dict content produces a valid (empty) SSE stream."""
        response = ResponseEnvelope(content=None, status_code=200)
        envelope = internlm_backend._wrap_as_streaming_envelope(response)

        chunks: list[ProcessedResponse] = []
        async for chunk in envelope.content:
            chunks.append(chunk)

        assert len(chunks) == 2
        # Content chunk should be a valid SSE event wrapping an empty-ish chunk
        first = chunks[0].content
        assert isinstance(first, bytes)
        assert first.startswith(b"data: ")
        # [DONE] sentinel
        assert chunks[1].content == b"data: [DONE]\n\n"


class TestInternLMChatCompletionsCanonical:
    """Test _chat_completions_canonical streaming shim behaviour."""

    async def test_non_streaming_request_passes_through(
        self, internlm_backend: InternLMConnector
    ):
        """Non-streaming request returns ResponseEnvelope unchanged."""
        fake_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Hi"}}]},
            status_code=200,
        )

        # Build a mock ConnectorChatCompletionsRequest
        from src.connectors.contracts import ConnectorChatCompletionsRequest
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        domain_request = CanonicalChatRequest(
            model="internlm/intern-s1-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=False,
        )
        request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=list(domain_request.messages),
            effective_model="internlm/intern-s1-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        with patch.object(
            InternLMConnector.__bases__[0],
            "_chat_completions_canonical",
            return_value=fake_response,
        ):
            result = await internlm_backend._chat_completions_canonical(request)

        assert isinstance(result, ResponseEnvelope)
        assert result is fake_response

    async def test_streaming_request_returns_streaming_envelope(
        self, internlm_backend: InternLMConnector
    ):
        """Streaming request converts ResponseEnvelope to StreamingResponseEnvelope."""
        fake_response = ResponseEnvelope(
            content={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "model": "intern-s1-pro",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Answer"},
                        "finish_reason": "stop",
                    }
                ],
            },
            status_code=200,
            headers={"x-backend": "internlm"},
        )

        from src.connectors.contracts import ConnectorChatCompletionsRequest
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        domain_request = CanonicalChatRequest(
            model="internlm/intern-s1-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )
        request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=list(domain_request.messages),
            effective_model="internlm/intern-s1-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        with patch.object(
            InternLMConnector.__bases__[0],
            "_chat_completions_canonical",
            return_value=fake_response,
        ):
            result = await internlm_backend._chat_completions_canonical(request)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"

        # Consume the stream and verify content
        chunks: list[ProcessedResponse] = []
        assert result.content is not None
        async for chunk in result.content:
            chunks.append(chunk)

        assert len(chunks) == 2

        # Verify the content chunk has the right structure
        first = chunks[0].content
        assert isinstance(first, bytes)
        json_str = first[len(b"data: ") : -len(b"\n\n")]
        parsed = json.loads(json_str)
        assert parsed["object"] == "chat.completion.chunk"
        assert parsed["choices"][0]["delta"]["content"] == "Answer"

        # Verify done sentinel
        assert chunks[1].content == b"data: [DONE]\n\n"

    async def test_streaming_request_does_not_mutate_original(
        self, internlm_backend: InternLMConnector
    ):
        """The original domain_request.stream flag is never mutated."""
        fake_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Ok"}}]},
            status_code=200,
        )

        from src.connectors.contracts import ConnectorChatCompletionsRequest
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        domain_request = CanonicalChatRequest(
            model="internlm/intern-s1-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )
        request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=list(domain_request.messages),
            effective_model="internlm/intern-s1-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        with patch.object(
            InternLMConnector.__bases__[0],
            "_chat_completions_canonical",
            return_value=fake_response,
        ):
            await internlm_backend._chat_completions_canonical(request)

        # Original frozen model is never mutated
        assert domain_request.stream is True

    async def test_parent_receives_non_streaming_request(
        self, internlm_backend: InternLMConnector
    ):
        """The parent's _chat_completions_canonical receives stream=False."""
        fake_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Ok"}}]},
            status_code=200,
        )

        from src.connectors.contracts import ConnectorChatCompletionsRequest
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        domain_request = CanonicalChatRequest(
            model="internlm/intern-s1-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )
        request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=list(domain_request.messages),
            effective_model="internlm/intern-s1-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        captured_request = None

        async def capture_parent_call(
            self_arg: Any, req: ConnectorChatCompletionsRequest
        ) -> ResponseEnvelope:
            nonlocal captured_request
            captured_request = req
            return fake_response

        with patch.object(
            InternLMConnector.__bases__[0],
            "_chat_completions_canonical",
            capture_parent_call,
        ):
            await internlm_backend._chat_completions_canonical(request)

        assert captured_request is not None
        assert captured_request.request.stream is False

    async def test_streaming_request_propagates_error(
        self, internlm_backend: InternLMConnector
    ):
        """Errors from the parent are propagated to the caller."""
        from src.connectors.contracts import ConnectorChatCompletionsRequest
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        domain_request = CanonicalChatRequest(
            model="internlm/intern-s1-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
        )
        request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=list(domain_request.messages),
            effective_model="internlm/intern-s1-pro",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
        )

        with (
            patch.object(
                InternLMConnector.__bases__[0],
                "_chat_completions_canonical",
                side_effect=RuntimeError("backend error"),
            ),
            pytest.raises(RuntimeError, match="backend error"),
        ):
            await internlm_backend._chat_completions_canonical(request)

        # stream flag must still be restored
        assert domain_request.stream is True
