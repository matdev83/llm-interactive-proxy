import pytest
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
)
from src.core.services.translation_service import TranslationService


class TestTranslationService:
    """Test the TranslationService."""

    def test_to_domain_request(self):
        """Test basic request translation."""
        service = TranslationService()
        req = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        domain_req = service.to_domain_request(req, "openai")
        assert isinstance(domain_req, CanonicalChatRequest)
        assert domain_req.model == "test-model"

    def test_from_domain_request(self):
        """Test basic domain to external request translation."""
        service = TranslationService()
        domain_req = CanonicalChatRequest(
            model="test-model", messages=[{"role": "user", "content": "hello"}]
        )
        external_req = service.from_domain_request(domain_req, "openai")
        assert isinstance(external_req, dict)
        assert external_req["model"] == "test-model"

    def test_to_domain_response(self):
        """Test basic response translation."""
        service = TranslationService()
        resp = {
            "id": "test",
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
        }
        domain_resp = service.to_domain_response(resp, "openai")
        assert isinstance(domain_resp, CanonicalChatResponse)
        assert domain_resp.model == "test-model"

    def test_from_domain_response(self):
        """Test basic domain to external response translation."""
        service = TranslationService()
        domain_resp = CanonicalChatResponse(
            id="test",
            created=123,  # Added missing required field
            model="test-model",
            choices=[
                {"index": 0, "message": {"role": "assistant", "content": "hi"}}
            ],  # Added missing required field 'index'
        )
        external_resp = service.from_domain_response(domain_resp, "openai")
        assert isinstance(external_resp, dict)
        assert external_resp["model"] == "test-model"

    def test_to_domain_stream_chunk_openai(self):
        """Test translation from OpenAI stream chunk format."""
        service = TranslationService()
        openai_chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": "gpt-4",
            "choices": [
                {"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}
            ],
        }
        domain_chunk = service.to_domain_stream_chunk(openai_chunk, "openai")
        assert isinstance(domain_chunk, CanonicalStreamChunk)
        assert domain_chunk.id == "chatcmpl-123"
        assert domain_chunk.choices[0].delta.content == "Hello"

    def test_to_domain_stream_chunk_code_assist(self):
        """Test translation from Code Assist stream chunk format."""
        service = TranslationService()
        code_assist_chunk = {
            "response": {
                "candidates": [{"content": {"parts": [{"text": "streaming text"}]}}]
            }
        }
        domain_chunk = service.to_domain_stream_chunk(code_assist_chunk, "code_assist")
        assert isinstance(domain_chunk, dict | CanonicalStreamChunk)
        assert domain_chunk["choices"][0]["delta"]["content"] == "streaming text"

    def test_to_domain_stream_chunk_gemini(self):
        """Test translation from Gemini stream chunk format."""
        service = TranslationService()
        gemini_chunk = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Gemini streaming"}]},
                    "finishReason": "STOP",
                }
            ]
        }

        domain_chunk = service.to_domain_stream_chunk(gemini_chunk, "gemini")

        assert isinstance(domain_chunk, CanonicalStreamChunk)
        assert domain_chunk.object == "chat.completion.chunk"
        assert domain_chunk.choices[0].delta.content == "Gemini streaming"
        assert domain_chunk.choices[0].finish_reason == "stop"

    def test_to_domain_request_raw_text(self):
        """Test translation from raw text format."""
        service = TranslationService()
        raw_text_request = "Hello world"
        domain_request = service.to_domain_request(raw_text_request, "raw_text")
        assert isinstance(domain_request, CanonicalChatRequest)
        assert domain_request.model == "text-model"
        assert domain_request.messages[0].content == "Hello world"

    def test_to_domain_response_raw_text(self):
        """Test translation from raw text response format."""
        service = TranslationService()
        raw_text_response = "Response text"
        domain_response = service.to_domain_response(raw_text_response, "raw_text")
        assert isinstance(domain_response, CanonicalChatResponse)
        assert domain_response.choices[0].message.content == "Response text"

    def test_to_domain_stream_chunk_raw_text(self):
        """Test translation from raw text stream chunk format."""
        service = TranslationService()
        raw_text_chunk = "Streaming part"
        domain_chunk = service.to_domain_stream_chunk(raw_text_chunk, "raw_text")
        assert isinstance(domain_chunk, CanonicalStreamChunk)
        assert domain_chunk.choices[0].delta.content == "Streaming part"

    def test_to_domain_stream_chunk_anthropic(self):
        """Test translation from Anthropic stream chunk format."""
        service = TranslationService()
        anthropic_chunk = {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello"},
        }
        domain_chunk = service.to_domain_stream_chunk(anthropic_chunk, "anthropic")
        # Anthropic chunks are still returned as dicts by Translation for now
        assert isinstance(domain_chunk, dict)
        assert domain_chunk["choices"][0]["delta"]["content"] == "Hello"

    def test_to_domain_stream_chunk_unsupported_format(self):
        """Test error handling for unsupported stream chunk format."""
        service = TranslationService()
        with pytest.raises(NotImplementedError):
            service.to_domain_stream_chunk({}, "unsupported")

    def test_from_domain_stream_chunk_openai(self):
        """Test translation from domain stream chunk to OpenAI format."""
        service = TranslationService()
        domain_chunk = CanonicalStreamChunk(
            id="test",
            object="chat.completion.chunk",
            created=123,
            model="test-model",
            choices=[
                {
                    "index": 0,
                    "delta": {"content": "Hello", "role": "assistant"},
                    "finish_reason": None,
                }
            ],
        )
        openai_chunk = service.from_domain_stream_chunk(domain_chunk, "openai")
        assert isinstance(openai_chunk, dict)
        assert openai_chunk["id"] == "test"
        assert openai_chunk["choices"][0]["delta"]["content"] == "Hello"

    def test_from_domain_stream_chunk_anthropic(self):
        """Test translation from domain stream chunk to Anthropic format."""
        service = TranslationService()
        domain_chunk = CanonicalStreamChunk(
            id="test",
            object="chat.completion.chunk",
            created=123,
            model="test-model",
            choices=[
                {
                    "index": 0,
                    "delta": {"content": "Hello", "role": "assistant"},
                    "finish_reason": None,
                }
            ],
        )
        anthropic_chunk = service.from_domain_stream_chunk(domain_chunk, "anthropic")
        assert isinstance(anthropic_chunk, dict)
        assert anthropic_chunk["type"] == "content_block_delta"
        assert anthropic_chunk["delta"]["text"] == "Hello"

    def test_from_domain_stream_chunk_gemini(self):
        """Test translation from domain stream chunk to Gemini format."""
        service = TranslationService()
        domain_chunk = CanonicalStreamChunk(
            id="test",
            object="chat.completion.chunk",
            created=123,
            model="test-model",
            choices=[
                {
                    "index": 0,
                    "delta": {"content": "Hello", "role": "assistant"},
                    "finish_reason": None,
                }
            ],
        )
        gemini_chunk = service.from_domain_stream_chunk(domain_chunk, "gemini")
        assert isinstance(gemini_chunk, dict)
        assert gemini_chunk["candidates"][0]["content"]["parts"][0]["text"] == "Hello"

    def test_from_domain_stream_chunk_unsupported_format(self):
        """Test error handling for unsupported target stream chunk format."""
        service = TranslationService()
        domain_chunk = CanonicalStreamChunk(
            id="test",
            object="chat.completion.chunk",
            created=123,
            model="test-model",
            choices=[],
        )
        with pytest.raises(NotImplementedError):
            service.from_domain_stream_chunk(domain_chunk, "unsupported")
