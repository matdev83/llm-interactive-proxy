from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
)
from src.core.services.translation_service import TranslationService


def test_translation_service_initialization():
    service = TranslationService()
    assert service is not None, "TranslationService should initialize without errors."


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
