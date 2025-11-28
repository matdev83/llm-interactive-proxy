import pytest
from src.connectors.gemini_oauth_base import GeminiOAuthBaseConnector
from src.core.common.exceptions import BackendError


class TestGeminiRateLimitRepro:
    def test_extract_retry_delay_failure_without_details(self):
        """
        Reproduces the issue where BackendError raised without 'details'
        causes _extract_retry_delay_from_error to fail.
        """
        # The error payload from the log
        error_payload = [
            {
                "error": {
                    "code": 429,
                    "message": "You have exhausted your capacity on this model. Your quota will reset after 2h21m41s.",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "QUOTA_EXHAUSTED",
                            "domain": "cloudcode-pa.googleapis.com",
                            "metadata": {
                                "quotaResetDelay": "2h21m41.46050292s",
                                "quotaResetTimeStamp": "2025-11-28T20:26:50Z",
                                "uiMessage": "true",
                                "model": "gemini-2.5-pro",
                            },
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "8501.460502920s",
                        },
                    ],
                }
            }
        ]

        # Current behavior in _handle_streaming_error: details are NOT passed
        error = BackendError(
            message=f"Code Assist API streaming error: {error_payload}",
            code="code_assist_error",
            status_code=429,
        )

        # Verify details is empty (default)
        assert error.details == {}

        # Attempt extraction
        delay = GeminiOAuthBaseConnector._extract_retry_delay_from_error(error)

        # Should fail (return None) because details are missing
        assert delay is None

    def test_extract_retry_delay_success_with_details(self):
        """
        Verifies that passing the error payload as 'details' allows extraction.
        """
        # The error payload from the log (list format)
        error_payload_list = [
            {
                "error": {
                    "code": 429,
                    "message": "You have exhausted your capacity on this model. Your quota will reset after 2h21m41s.",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "QUOTA_EXHAUSTED",
                            "domain": "cloudcode-pa.googleapis.com",
                            "metadata": {
                                "quotaResetDelay": "2h21m41.46050292s",
                                "quotaResetTimeStamp": "2025-11-28T20:26:50Z",
                                "uiMessage": "true",
                                "model": "gemini-2.5-pro",
                            },
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "8501.460502920s",
                        },
                    ],
                }
            }
        ]

        # Proposed fix: Extract the dict from the list and pass as details
        details = error_payload_list[0]

        error = BackendError(
            message=f"Code Assist API streaming error: {error_payload_list}",
            code="code_assist_error",
            status_code=429,
            details=details,
        )

        # Attempt extraction
        delay = GeminiOAuthBaseConnector._extract_retry_delay_from_error(error)

        # Should succeed.
        # quotaResetDelay: 2h21m41.46050292s
        # 2h = 7200s
        # 21m = 1260s
        # 41.46s
        # Total = 8501.46s

        assert delay is not None
        assert delay == pytest.approx(8501.46, 0.01)

    def test_extract_retry_delay_from_retry_info(self):
        """
        Verifies extraction from retryDelay if quotaResetDelay is missing.
        """
        details = {
            "error": {
                "code": 429,
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "100s",
                    }
                ],
            }
        }

        error = BackendError(message="Error", details=details)

        delay = GeminiOAuthBaseConnector._extract_retry_delay_from_error(error)
        assert delay == 100.0
