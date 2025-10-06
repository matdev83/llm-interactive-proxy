"""
Test quota exceeded detection for Gemini OAuth Personal connector.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector
from src.core.common.exceptions import BackendError


class TestGeminiOAuthPersonalQuotaDetection:
    """Test quota exceeded detection functionality."""

    @pytest.fixture
    def connector(self) -> GeminiOAuthPersonalConnector:
        """Create a GeminiOAuthPersonalConnector instance for testing."""
        with (
            patch("src.connectors.gemini_oauth_personal.httpx.AsyncClient"),
            patch("src.connectors.gemini_oauth_personal.TranslationService"),
            patch("src.connectors.gemini_oauth_personal.AppConfig"),
        ):

            from src.core.config.app_config import AppConfig

            mock_config = Mock(spec=AppConfig)
            mock_config.gemini_cli_oauth_path = None

            client = Mock()
            translation_service = Mock()

            return GeminiOAuthPersonalConnector(
                client=client,
                config=mock_config,
                translation_service=translation_service,
            )

    def test_mark_backend_unusable_sets_flags(
        self, connector: GeminiOAuthPersonalConnector
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
        # Test case 1: Exact quota exceeded error (should match)
        error_detail_1 = {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests' and limit 'Gemini 2.5 Pro Requests per day per user per tier' of service 'cloudcode-pa.googleapis.com' for consumer 'project_number:681255809395'.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        status_code_1 = 429
        message_1 = error_detail_1.get("error", {}).get("message", "")

        condition_matches_1 = (
            status_code_1 == 429
            and isinstance(error_detail_1, dict)
            and "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'" in message_1
        )

        assert condition_matches_1 is True

        # Test case 2: Different 429 error (should not match)
        error_detail_2 = {
            "error": {
                "code": 429,
                "message": "Rate limit exceeded. Try again in 60 seconds.",
                "status": "RESOURCE_EXHAUSTED",
            }
        }

        status_code_2 = 429
        message_2 = error_detail_2.get("error", {}).get("message", "")

        condition_matches_2 = (
            status_code_2 == 429
            and isinstance(error_detail_2, dict)
            and "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'" in message_2
        )

        assert condition_matches_2 is False

        # Test case 3: Different status code (should not match)
        error_detail_3 = {
            "error": {
                "code": 500,
                "message": "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests' and limit 'Gemini 2.5 Pro Requests per day per user per tier' of service 'cloudcode-pa.googleapis.com' for consumer 'project_number:681255809395'.",
                "status": "INTERNAL_ERROR",
            }
        }

        status_code_3 = 500
        message_3 = error_detail_3.get("error", {}).get("message", "")

        condition_matches_3 = (
            status_code_3 == 429
            and isinstance(error_detail_3, dict)
            and "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'" in message_3
        )

        assert condition_matches_3 is False

    def test_quota_exceeded_error_marks_backend_unusable(
        self, connector: GeminiOAuthPersonalConnector
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

        # Verify backend was marked as unusable
        assert not connector.is_functional
        assert connector._quota_exceeded

        # Verify the exception details
        assert exc_info.value.code == "quota_exceeded"
        assert "quota exceeded" in str(exc_info.value).lower()

    def test_non_quota_error_does_not_mark_backend_unusable(
        self, connector: GeminiOAuthPersonalConnector
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

    @pytest.mark.asyncio
    async def test_streaming_quota_error_propagates_backend_error(
        self, connector: GeminiOAuthPersonalConnector
    ) -> None:
        """Ensure streaming quota errors are surfaced to callers."""
        connector.is_functional = True
        connector._oauth_credentials = {"access_token": "token"}
        connector.gemini_api_base_url = "https://example.com"
        connector._discover_project_id = AsyncMock(return_value="test-project")
        connector._refresh_token_if_needed = AsyncMock(return_value=True)
        connector.translation_service.from_domain_to_gemini_request.return_value = {
            "contents": [],
            "generationConfig": {},
        }
        connector.translation_service.to_domain_stream_chunk.return_value = {
            "choices": [],
        }
        connector._request_counter = Mock()
        connector._request_counter.increment = Mock()

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

        dummy_session = DummySession()

        with (
            patch(
                "src.connectors.gemini_oauth_personal.google.auth.transport.requests.AuthorizedSession",
                return_value=dummy_session,
            ),
            patch(
                "src.connectors.gemini_oauth_personal.asyncio.to_thread",
                async_to_thread,
            ),
            patch(
                "src.connectors.gemini_oauth_personal.tiktoken.get_encoding"
            ) as mock_encoding,
        ):
            mock_encoding.return_value = Mock()
            mock_encoding.return_value.encode.return_value = []

            request = Mock()
            request.stream = True
            request.messages = []
            request.extra_body = {}

            envelope = await connector._chat_completions_code_assist_streaming(
                request, [], "gemini-2.5-pro"
            )

            stream = envelope.content
            with pytest.raises(BackendError):
                await stream.__anext__()
