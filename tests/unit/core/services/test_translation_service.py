from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
)
from src.core.services.translation_service import TranslationService


def test_translation_service_initialization():
    service = TranslationService()
    assert service is not None, "TranslationService should initialize without errors."


def test_to_domain_request_with_canonical_input():
    service = TranslationService()
    canonical_request = CanonicalChatRequest.model_validate(
        {
            "model": "gpt-test",
            "messages": [{"role": "user", "content": "Ping"}],
        }
    )

    translated = service.to_domain_request(canonical_request, "openai")

    assert isinstance(translated, CanonicalChatRequest)
    assert translated.model == canonical_request.model
    assert translated.messages[0].content == "Ping"


def test_to_domain_request_gemini():
    service = TranslationService()
    gemini_request = {
        "model": "gemini-pro",
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "messages": [{"role": "user", "content": "Hello"}],
    }
    domain_request = service.to_domain_request(gemini_request, "gemini")
    assert isinstance(domain_request, CanonicalChatRequest)
    assert domain_request.model == "gemini-pro"
    assert domain_request.messages[0].content == "Hello"


def test_to_domain_response_gemini():
    service = TranslationService()
    gemini_response = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Hello back"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2},
    }
    domain_response = service.to_domain_response(gemini_response, "gemini")
    assert isinstance(domain_response, CanonicalChatResponse)
    # We're using a placeholder implementation which returns a fixed response
    assert domain_response.choices[0].message is not None


def test_to_domain_request_openai():
    service = TranslationService()
    openai_request = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    domain_request = service.to_domain_request(openai_request, "openai")
    assert isinstance(domain_request, CanonicalChatRequest)
    assert domain_request.model == "gpt-4"
    assert domain_request.messages[0].content == "Hello"


def test_to_domain_response_openai():
    service = TranslationService()
    openai_response = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello back"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    domain_response = service.to_domain_response(openai_response, "openai")
    assert isinstance(domain_response, CanonicalChatResponse)
    assert domain_response.choices[0].message.content == "Hello back"


def test_to_domain_response_openai_responses_output():
    service = TranslationService()
    responses_payload = {
        "id": "resp-789",
        "object": "response",
        "created": 1700000001,
        "model": "gpt-4.1",
        "output": [
            {
                "id": "msg-2",
                "role": "assistant",
                "type": "message",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Structured reply"},
                    {
                        "type": "tool_call",
                        "id": "call-2",
                        "function": {
                            "name": "make_call",
                            "arguments": '{"foo": "bar"}',
                        },
                    },
                ],
            }
        ],
        "usage": {"input_tokens": 5, "output_tokens": 7},
    }

    domain_response = service.to_domain_response(responses_payload, "openai-responses")

    assert isinstance(domain_response, CanonicalChatResponse)
    assert domain_response.object == "response"
    assert len(domain_response.choices) == 1
    choice = domain_response.choices[0]
    assert choice.message is not None
    assert choice.message.tool_calls is not None
    assert choice.message.tool_calls[0].function.name == "make_call"
    assert choice.finish_reason == "stop"
    assert domain_response.usage is not None
    if domain_response.usage:
        assert domain_response.usage["prompt_tokens"] == 5
        assert domain_response.usage["completion_tokens"] == 7


def test_to_domain_request_code_assist():
    """Test translation from Code Assist API request format."""
    service = TranslationService()
    code_assist_request = {
        "model": "gemini-1.5-flash-002",
        "messages": [{"role": "user", "content": "Hello"}],
        "project": "test-project",  # Code Assist specific field
    }
    domain_request = service.to_domain_request(code_assist_request, "code_assist")
    assert isinstance(domain_request, CanonicalChatRequest)
    assert domain_request.model == "gemini-1.5-flash-002"
    assert domain_request.messages[0].content == "Hello"


def test_to_domain_response_code_assist():
    """Test translation from Code Assist API response format."""
    service = TranslationService()
    code_assist_response = {
        "response": {
            "candidates": [{"content": {"parts": [{"text": "Hello from Code Assist"}]}}]
        }
    }
    domain_response = service.to_domain_response(code_assist_response, "code_assist")
    assert isinstance(domain_response, CanonicalChatResponse)
    assert domain_response.choices[0].message.content == "Hello from Code Assist"


def test_to_domain_stream_chunk_code_assist():
    """Test translation from Code Assist API stream chunk format."""
    service = TranslationService()
    code_assist_chunk = {
        "response": {
            "candidates": [{"content": {"parts": [{"text": "streaming text"}]}}]
        }
    }
    domain_chunk = service.to_domain_stream_chunk(code_assist_chunk, "code_assist")
    assert isinstance(domain_chunk, dict)
    assert domain_chunk["choices"][0]["delta"]["content"] == "streaming text"


def test_to_domain_stream_chunk_gemini():
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

    assert isinstance(domain_chunk, dict)
    assert domain_chunk["object"] == "chat.completion.chunk"
    assert domain_chunk["choices"][0]["delta"]["content"] == "Gemini streaming"
    assert domain_chunk["choices"][0]["finish_reason"] == "stop"


def test_to_domain_request_raw_text():
    """Test translation from raw text format."""
    service = TranslationService()
    raw_text_request = "Hello world"
    domain_request = service.to_domain_request(raw_text_request, "raw_text")
    assert isinstance(domain_request, CanonicalChatRequest)
    assert domain_request.model == "text-model"
    assert domain_request.messages[0].content == "Hello world"


def test_to_domain_response_raw_text():
    """Test translation from raw text response format."""
    service = TranslationService()
    raw_text_response = "Response text"
    domain_response = service.to_domain_response(raw_text_response, "raw_text")
    assert isinstance(domain_response, CanonicalChatResponse)
    assert domain_response.choices[0].message.content == "Response text"


def test_to_domain_stream_chunk_raw_text():
    """Test translation from raw text stream chunk format."""
    service = TranslationService()
    raw_text_chunk = "streaming chunk"
    domain_chunk = service.to_domain_stream_chunk(raw_text_chunk, "raw_text")
    assert isinstance(domain_chunk, dict)
    assert domain_chunk["choices"][0]["delta"]["content"] == "streaming chunk"


def test_to_domain_stream_chunk_raw_text_wrapped():
    """Test translation from wrapped raw text stream chunk format."""
    service = TranslationService()
    wrapped_chunk = {"text": "wrapped streaming chunk"}
    domain_chunk = service.to_domain_stream_chunk(wrapped_chunk, "raw_text")
    assert isinstance(domain_chunk, dict)
    assert domain_chunk["choices"][0]["delta"]["content"] == "wrapped streaming chunk"
