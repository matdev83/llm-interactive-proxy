"""
Test quota exceeded detection for Gemini OAuth Personal connector.
"""

from typing import cast
from unittest.mock import AsyncMock, Mock, create_autospec, patch

import pytest
from src.connectors.gemini_oauth_free import GeminiOAuthFreeConnector
from src.connectors.utils.gemini_request_counter import DailyRequestCounter
from src.core.common.exceptions import BackendError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestGeminiOAuthFreeQuotaDetection:
    """Test quota exceeded detection functionality."""

    @pytest.fixture
    def connector(self) -> GeminiOAuthFreeConnector:
        """Create a GeminiOAuthFreeConnector instance for testing."""
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        mock_config = Mock(spec=AppConfig)
        mock_config.gemini_cli_oauth_path = None

        client = Mock()
        translation_service = create_autospec(TranslationService, instance=True)

        return GeminiOAuthFreeConnector(
            client=client,
            config=mock_config,
            translation_service=translation_service,
        )

    def test_mark_backend_unusable_sets_flags(
        self, connector: GeminiOAuthFreeConnector
    ) -> None:
        """Test that _mark_backend_unusable sets the correct flags."""
        # Initially, the backend should be non-functional but not quota exceeded
        assert not connector.is_functional
        assert not connector._quota_exceeded

        # Mark backend as unusable
        connector._mark_backend_unusable()

        # Should still be non-functional and now quota exceeded
        assert not connector.is_functional
        assert connector._quota_exceeded

    def test_quota_exceeded_detection_condition_matches(self) -> None:
        """Test that the quota exceeded detection condition correctly identifies quota errors."""

        def condition_matches(status_code: int, error_detail: dict) -> bool:
            message = error_detail.get("error", {}).get("message", "")
            message_lower = message.lower()
            return (
                status_code == 429
                and isinstance(error_detail, dict)
                and (
                    "quota exceeded" in message_lower
                    or "resource exhausted" in message_lower
                    or "allowance" in message_lower
                )
            )

        # Test case 1: Exact quota exceeded error (should match)
        error_detail_1 = {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests' and limit 'Gemini 2.5 Pro Requests per day per user per tier' of service 'cloudcode-pa.googleapis.com' for consumer 'project_number:681255809395'.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        assert condition_matches(429, error_detail_1) is True

        # Test case 2: Resource exhausted message (should match)
        error_detail_2 = {
            "error": {
                "code": 429,
                "message": "Resource exhausted. Please try again later.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        assert condition_matches(429, error_detail_2) is True

        # Test case 3: Different 429 error (should not match)
        error_detail_3 = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded. Try again in 60 seconds.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        assert condition_matches(429, error_detail_3) is False

        # Test case 4: Different status code (should not match)
        error_detail_4 = {
            "error": {
                "code": 500,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests' and limit 'Gemini 2.5 Pro Requests per day per user per tier' of service 'cloudcode-pa.googleapis.com' for consumer 'project_number:681255809395'.",
                "status": "INTERNAL_ERROR",
            }
        }

        assert condition_matches(500, error_detail_4) is False

    def test_quota_exceeded_error_marks_backend_unusable(
        self, connector: GeminiOAuthFreeConnector
    ) -> None:
        """Test that quota exceeded errors mark the backend as unusable."""
        # Mock a response with quota exceeded error
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests' and limit 'Gemini 2.5 Pro Requests per day per user per tier' of service 'cloudcode-pa.googleapis.com' for consumer 'project_number:681255809395'.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        # Initially not quota exceeded
        assert not connector._quota_exceeded

        # Call the error handling method and expect a BackendError
        with pytest.raises(BackendError) as exc_info:
            connector._handle_streaming_error(mock_response)

        # Verify quota exceeded flag was set but backend stays functional for other models
        # (is_functional may be False before initialization, but _quota_exceeded should be True)
        assert connector._quota_exceeded

        # Verify the exception details
        assert exc_info.value.code == "quota_exceeded"
        assert "quota exceeded" in str(exc_info.value).lower()

    def test_non_quota_error_does_not_mark_backend_unusable(
        self, connector: GeminiOAuthFreeConnector
    ) -> None:
        """Test that non-quota 429 errors do not mark the backend as unusable."""
        # Mock a response with regular rate limit error
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded. Try again in 60 seconds.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        # Initially not quota exceeded
        assert not connector._quota_exceeded

        # Call the error handling method and expect a BackendError
        with pytest.raises(BackendError) as exc_info:
            connector._handle_streaming_error(mock_response)

        # Verify backend was NOT marked as unusable
        assert not connector._quota_exceeded

        # Verify the exception details
        assert exc_info.value.code == "code_assist_error"
        assert "quota exceeded" not in str(exc_info.value).lower()

    def test_resource_exhausted_error_marks_backend_unusable(
        self, connector: GeminiOAuthFreeConnector
    ) -> None:
        """Test that resource exhausted errors are treated as quota exhaustion."""

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = {
            "error": {
                "code": 429,
                "message": "Resource exhausted. Please try again later.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        with pytest.raises(BackendError) as exc_info:
            connector._handle_streaming_error(mock_response)

        # Verify quota exceeded flag was set but backend stays functional for other models
        assert connector._quota_exceeded
        assert exc_info.value.code == "quota_exceeded"
        assert "quota exhausted" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_streaming_quota_error_propagates_backend_error(
        self, connector: GeminiOAuthFreeConnector
    ) -> None:
        """Ensure streaming quota errors are surfaced to callers."""
        connector.is_functional = True
        connector._oauth_credentials = {"access_token": "token"}
        connector.gemini_api_base_url = "https://example.com"
        connector._discover_project_id = AsyncMock(return_value="test-project")  # type: ignore[method-assign]
        connector._refresh_token_if_needed = AsyncMock(return_value=True)  # type: ignore[method-assign]
        connector._request_counter = _build_counter_mock(connector._request_counter)

        quota_error = {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.json.return_value = quota_error
        mock_response.text = "quota exceeded"

        async_to_thread = AsyncMock(return_value=mock_response)

        class DummySession:
            def __init__(self) -> None:
                self.request = Mock()
                self.headers: dict[str, str] = {}

        dummy_session = DummySession()

        with (
            patch(
                "google.auth.transport.requests.AuthorizedSession",
                return_value=dummy_session,
            ),
            patch(
                "src.connectors.gemini_oauth_free.asyncio.to_thread",
                async_to_thread,
            ),
            patch(
                "src.connectors.gemini_oauth_base.tiktoken.get_encoding"
            ) as mock_encoding,
            patch.object(
                connector.translation_service,
                "from_domain_to_gemini_request",
                return_value={"contents": [], "generationConfig": {}},
            ),
            patch.object(
                connector.translation_service,
                "to_domain_stream_chunk",
                return_value={"choices": []},
            ),
        ):
            mock_encoding.return_value = Mock()
            mock_encoding.return_value.encode.return_value = []

            request = CanonicalChatRequest(
                model="gemini-2.5-pro",
                messages=[ChatMessage(role="user", content="hello")],
                stream=True,
            )

            envelope = await connector._chat_completions_code_assist_streaming(
                request, [], "gemini-2.5-pro"
            )

            stream = envelope.content
            chunk = await stream.__anext__()
            assert isinstance(chunk, ProcessedResponse)
            assert chunk.content
            assert chunk.content["error"]["code"] == 503
            assert (
                "service temporarily unavailable"
                in chunk.content["error"]["message"].lower()
            )


def _build_counter_mock(counter: DailyRequestCounter | None) -> DailyRequestCounter:
    mock_counter = create_autospec(DailyRequestCounter, instance=True)
    mock_counter.increment.return_value = None
    return cast(DailyRequestCounter, mock_counter)
