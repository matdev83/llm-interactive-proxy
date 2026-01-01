# import json # F401: Removed

import httpx
import pytest
import pytest_asyncio
from src.connectors.openrouter import OpenRouterBackend

# from pytest_httpx import HTTPXMock # F401: Removed
from src.core.domain.chat import ChatMessage, ChatRequest

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(_: str, api_key: str) -> dict[str, str]:
    # Create a mock config dictionary for testing
    mock_config = {
        "app_site_url": "http://localhost:test",
        "app_x_title": "TestProxy",
    }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": mock_config["app_site_url"],
        "X-Title": mock_config["app_x_title"],
    }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        # Create a mock TranslationService
        mock_translation_service = TranslationService()
        backend = OpenRouterBackend(
            client=client, config=config, translation_service=mock_translation_service
        )
        # Call initialize with required arguments
        await backend.initialize(
            api_key="test_key",  # A dummy API key for initialization
            key_name="openrouter",
            openrouter_headers_provider=mock_get_openrouter_headers,
        )
        yield backend


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    """Return a minimal chat request without optional fields set."""
    return ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content="Hello")]
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_http_error_streaming(
    monkeypatch: pytest.MonkeyPatch,  # Add monkeypatch fixture
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": True}
    )
    error_text_response = "OpenRouter internal server error"

    async def mock_send_method(self, request, **kwargs):
        class MockResponse:
            def __init__(self, status_code, request, stream, headers) -> None:
                self.status_code = status_code
                self.request = request
                self.stream = stream
                self.headers = headers
                self._read = False

            async def aclose(self):
                pass

            async def aread(self):
                if not self._read:
                    self._read = True
                    return error_text_response.encode("utf-8")
                return b""

            @property
            def text(self):
                return error_text_response

        return MockResponse(
            status_code=500,
            request=request,
            stream=httpx.ByteStream(error_text_response.encode("utf-8")),
            headers={"Content-Type": "text/plain"},
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", mock_send_method)

    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        # Create a mock TranslationService
        mock_translation_service = TranslationService()
        openrouter_backend = OpenRouterBackend(
            client=client, config=config, translation_service=mock_translation_service
        )
        # Initialize the backend
        await openrouter_backend.initialize(
            api_key="FAKE_KEY",
            key_name="test_key",
            openrouter_headers_provider=mock_get_openrouter_headers,
        )

        # The error is converted to a StreamingContent chunk, not raised as an exception
        response = await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model="test-model",
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers,
            key_name="test_key",
            api_key="FAKE_KEY",
        )
        
        # The error is caught and handled by error_mapping service
        # The test verifies that HTTP 500 errors are handled gracefully
        # The error is logged (visible in test output), and the stream should
        # either contain an error chunk or terminate gracefully
        
        assert hasattr(response, "content") and response.content, "Response should have content"
        chunks = []
        
        try:
            async for chunk in response.content:
                chunks.append(chunk)
        except Exception:
            # Exception during consumption is acceptable - error was handled
            pass
        
        # Check chunks for error indicators
        has_error = False
        error_message_found = False
        
        for chunk in chunks:
            # Check metadata for error
            if hasattr(chunk, "metadata") and chunk.metadata:
                if "error" in chunk.metadata:
                    has_error = True
                    error_info = chunk.metadata.get("error")
                    if isinstance(error_info, dict):
                        error_msg = str(error_info.get("message", ""))
                        assert error_info.get("code") == 500 or "500" in error_msg or "OpenRouter internal server error" in error_msg
                        error_message_found = True
                        break
                if chunk.metadata.get("finish_reason") == "error":
                    has_error = True
                    break
            # Check content for error structure
            content = chunk.content if hasattr(chunk, "content") else None
            if isinstance(content, dict):
                if "error" in content:
                    has_error = True
                    error_info = content.get("error")
                    if isinstance(error_info, dict):
                        error_msg = str(error_info.get("message", ""))
                        assert error_info.get("code") == 500 or "500" in error_msg or "OpenRouter internal server error" in error_msg
                        error_message_found = True
                        break
            elif isinstance(content, bytes):
                # Parse SSE-formatted content
                content_str = content.decode("utf-8", errors="ignore")
                if '"finish_reason": "error"' in content_str or '"error":' in content_str:
                    has_error = True
                    if "OpenRouter internal server error" in content_str or '"code": 500' in content_str or '"status_code": 500' in content_str:
                        error_message_found = True
                        break
            elif isinstance(content, str) and (
                '"finish_reason": "error"' in content or '"error":' in content
            ):
                has_error = True
                if (
                    "OpenRouter internal server error" in content
                    or '"code": 500' in content
                    or '"status_code": 500' in content
                ):
                    error_message_found = True
                    break
        
        # Verify error was properly handled and contains expected message
        assert has_error, (
            f"Error should be indicated in stream. "
            f"Got {len(chunks)} chunks. "
            f"First chunk content type: {type(chunks[0].content).__name__ if chunks else 'N/A'}, "
            f"content preview: {str(chunks[0].content)[:200] if chunks else 'N/A'}"
        )
        assert error_message_found or "OpenRouter internal server error" in str(chunks[0].content) if chunks else False, (
            "Error message should mention 'OpenRouter internal server error' or contain status code 500"
        )
