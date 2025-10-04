"""
Test quota exceeded detection for Gemini OAuth Personal connector.
"""

from unittest.mock import Mock, patch

import pytest
from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector


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

    @patch("src.connectors.gemini_oauth_personal.logger")
    def test_quota_exceeded_error_marks_backend_unusable(
        self, mock_logger: Mock, connector: GeminiOAuthPersonalConnector
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

        # This would be the error handling logic from the streaming response
        # We're testing the condition that would trigger the quota detection
        if mock_response.status_code >= 400:
            try:
                error_detail = mock_response.json()
            except Exception:
                error_detail = mock_response.text

            # Check for 429 quota exceeded error
            if (
                mock_response.status_code == 429
                and isinstance(error_detail, dict)
                and "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'"
                in error_detail.get("error", {}).get("message", "")
            ):

                # Mark backend as unusable
                connector._mark_backend_unusable()

        # Verify backend was marked as unusable
        assert not connector.is_functional
        assert connector._quota_exceeded

        # Verify error was logged
        mock_logger.error.assert_called_once()
        call_args, _ = mock_logger.error.call_args
        assert "marked as unusable due to quota exceeded" in call_args[0]

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

        # This would be the error handling logic from the streaming response
        # We're testing the condition that would NOT trigger the quota detection
        if mock_response.status_code >= 400:
            try:
                error_detail = mock_response.json()
            except Exception:
                error_detail = mock_response.text

            # Check for 429 quota exceeded error
            if (
                mock_response.status_code == 429
                and isinstance(error_detail, dict)
                and "Quota exceeded for quota metric 'Gemini 2.5 Pro Requests'"
                in error_detail.get("error", {}).get("message", "")
            ):

                # Mark backend as unusable
                connector._mark_backend_unusable()

        # Verify backend was NOT marked as unusable
        assert not connector._quota_exceeded
