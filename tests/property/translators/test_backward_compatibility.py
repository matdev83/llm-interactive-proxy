from unittest.mock import MagicMock, patch

import pytest
from src.core.domain.translation import Translation
from src.core.interfaces.translator_protocol import TranslatorProtocol


@pytest.fixture
def mock_registry():
    with patch(
        "src.core.domain.translation.get_global_translator_registry"
    ) as mock_get:
        registry = MagicMock()
        mock_get.return_value = registry
        yield registry


def test_translation_facade_delegates_gemini_request(mock_registry):
    """Verify Translation.gemini_to_domain_request delegates to gemini translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {"contents": []}
    Translation.gemini_to_domain_request(request)

    mock_registry.get.assert_called_with("gemini")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_anthropic_request(mock_registry):
    """Verify Translation.anthropic_to_domain_request delegates to anthropic translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {"messages": []}
    Translation.anthropic_to_domain_request(request)

    mock_registry.get.assert_called_with("anthropic")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_anthropic_response(mock_registry):
    """Verify Translation.anthropic_to_domain_response delegates to anthropic translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {"content": []}
    Translation.anthropic_to_domain_response(response)

    mock_registry.get.assert_called_with("anthropic")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_gemini_response(mock_registry):
    """Verify Translation.gemini_to_domain_response delegates to gemini translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {"candidates": []}
    Translation.gemini_to_domain_response(response)

    mock_registry.get.assert_called_with("gemini")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_gemini_stream_chunk(mock_registry):
    """Verify Translation.gemini_to_domain_stream_chunk delegates to gemini translator."""
    translator = MagicMock()  # Streaming translator
    mock_registry.get.return_value = translator

    chunk = {"candidates": []}
    Translation.gemini_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("gemini")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_openai_request(mock_registry):
    """Verify Translation.openai_to_domain_request delegates to openai translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {"messages": []}
    Translation.openai_to_domain_request(request)

    mock_registry.get.assert_called_with("openai")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_openai_response(mock_registry):
    """Verify Translation.openai_to_domain_response delegates to openai translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {"choices": []}
    Translation.openai_to_domain_response(response)

    mock_registry.get.assert_called_with("openai")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_responses_response(mock_registry):
    """Verify Translation.responses_to_domain_response delegates to responses translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {"output": {}}
    Translation.responses_to_domain_response(response)

    mock_registry.get.assert_called_with("responses")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_openai_stream_chunk(mock_registry):
    """Verify Translation.openai_to_domain_stream_chunk delegates to openai translator."""
    translator = MagicMock()
    mock_registry.get.return_value = translator

    chunk = {"choices": []}
    Translation.openai_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("openai")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_responses_stream_chunk(mock_registry):
    """Verify Translation.responses_to_domain_stream_chunk delegates to responses translator."""
    translator = MagicMock()
    mock_registry.get.return_value = translator

    chunk = {"output": {}}
    Translation.responses_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("responses")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_openrouter_request(mock_registry):
    """Verify Translation.openrouter_to_domain_request delegates to openrouter translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {"messages": []}
    Translation.openrouter_to_domain_request(request)

    mock_registry.get.assert_called_with("openrouter")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_from_domain_to_gemini_request(mock_registry):
    """Verify Translation.from_domain_to_gemini_request delegates to gemini translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = MagicMock()
    Translation.from_domain_to_gemini_request(request)

    mock_registry.get.assert_called_with("gemini")
    translator.from_domain_request.assert_called_with(request)


def test_translation_facade_delegates_from_domain_to_openai_request(mock_registry):
    """Verify Translation.from_domain_to_openai_request delegates to openai translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = MagicMock()
    Translation.from_domain_to_openai_request(request)

    mock_registry.get.assert_called_with("openai")
    translator.from_domain_request.assert_called_with(request)


def test_translation_facade_delegates_anthropic_stream_chunk(mock_registry):
    """Verify Translation.anthropic_to_domain_stream_chunk delegates to anthropic translator."""
    translator = MagicMock()
    mock_registry.get.return_value = translator

    chunk = {}
    Translation.anthropic_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("anthropic")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_from_domain_to_anthropic_request(mock_registry):
    """Verify Translation.from_domain_to_anthropic_request delegates to anthropic translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = MagicMock()
    Translation.from_domain_to_anthropic_request(request)

    mock_registry.get.assert_called_with("anthropic")
    translator.from_domain_request.assert_called_with(request)


def test_translation_facade_delegates_code_assist_request(mock_registry):
    """Verify Translation.code_assist_to_domain_request delegates to code_assist translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {}
    Translation.code_assist_to_domain_request(request)

    mock_registry.get.assert_called_with("code_assist")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_code_assist_response(mock_registry):
    """Verify Translation.code_assist_to_domain_response delegates to code_assist translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {}
    Translation.code_assist_to_domain_response(response)

    mock_registry.get.assert_called_with("code_assist")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_code_assist_stream_chunk(mock_registry):
    """Verify Translation.code_assist_to_domain_stream_chunk delegates to code_assist translator."""
    translator = MagicMock()
    mock_registry.get.return_value = translator

    chunk = {}
    Translation.code_assist_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("code_assist")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_raw_text_request(mock_registry):
    """Verify Translation.raw_text_to_domain_request delegates to raw_text translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {}
    Translation.raw_text_to_domain_request(request)

    mock_registry.get.assert_called_with("raw_text")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_raw_text_response(mock_registry):
    """Verify Translation.raw_text_to_domain_response delegates to raw_text translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = {}
    Translation.raw_text_to_domain_response(response)

    mock_registry.get.assert_called_with("raw_text")
    translator.to_domain_response.assert_called_with(response)


def test_translation_facade_delegates_raw_text_stream_chunk(mock_registry):
    """Verify Translation.raw_text_to_domain_stream_chunk delegates to raw_text translator."""
    translator = MagicMock()
    mock_registry.get.return_value = translator

    chunk = {}
    Translation.raw_text_to_domain_stream_chunk(chunk)

    mock_registry.get.assert_called_with("raw_text")
    translator.to_domain_stream_chunk.assert_called_with(chunk)


def test_translation_facade_delegates_responses_request(mock_registry):
    """Verify Translation.responses_to_domain_request delegates to responses translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = {}
    Translation.responses_to_domain_request(request)

    mock_registry.get.assert_called_with("responses")
    translator.to_domain_request.assert_called_with(request)


def test_translation_facade_delegates_from_domain_to_responses_response(mock_registry):
    """Verify Translation.from_domain_to_responses_response delegates to responses translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    response = MagicMock()
    Translation.from_domain_to_responses_response(response)

    mock_registry.get.assert_called_with("responses")
    translator.from_domain_response.assert_called_with(response)


def test_translation_facade_delegates_from_domain_to_responses_request(mock_registry):
    """Verify Translation.from_domain_to_responses_request delegates to responses translator."""
    translator = MagicMock(spec=TranslatorProtocol)
    mock_registry.get.return_value = translator

    request = MagicMock()
    Translation.from_domain_to_responses_request(request)

    mock_registry.get.assert_called_with("responses")
    translator.from_domain_request.assert_called_with(request)
