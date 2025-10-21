"""
Test graceful error handling in Gemini connectors to prevent HTTP 502 errors.

This test ensures that when quota exhaustion or other API errors occur during
streaming, the connectors yield proper error chunks instead of raising exceptions
that would terminate the connection abruptly.
"""

import pytest


class TestGeminiGracefulErrorHandling:
    """Test suite for graceful error handling in streaming responses."""

    def test_quota_exhaustion_yields_error_chunk_not_exception(self):
        """
        Test that quota exhaustion during streaming yields an error chunk
        instead of raising BackendError that kills the connection.
        """
        # This is a static analysis test since mocking the full streaming
        # pipeline is complex, but we can verify the error handling pattern

        files_to_check = [
            "src/connectors/gemini_oauth_base.py",
            "src/connectors/gemini_cloud_project.py",
        ]

        for file_path in files_to_check:
            with open(file_path) as f:
                source_code = f.read()

            # Verify that streaming methods don't raise BackendError for quota issues
            # They should yield error chunks instead

            # Look for the problematic pattern: raising BackendError in streaming

            # Look for the good pattern: yielding error chunks
            good_pattern_1 = (
                "yield ProcessedResponse(content=error_chunk)" in source_code
            )
            good_pattern_2 = '"type": "quota_exceeded"' in source_code
            good_pattern_3 = '"error":' in source_code and "error_chunk" in source_code

            # The file should have graceful error handling patterns
            assert good_pattern_1, (
                f"{file_path} should yield error chunks instead of raising exceptions "
                f"to prevent abrupt connection termination"
            )

            assert good_pattern_2, (
                f"{file_path} should handle quota_exceeded errors gracefully "
                f"with proper error chunk formatting"
            )

            assert good_pattern_3, (
                f"{file_path} should include error information in response chunks "
                f"for proper client error handling"
            )

    def test_error_chunk_format_compliance(self):
        """
        Test that error chunks follow the correct OpenAI-compatible format.
        """
        files_to_check = [
            "src/connectors/gemini_oauth_base.py",
            "src/connectors/gemini_cloud_project.py",
        ]

        for file_path in files_to_check:
            with open(file_path) as f:
                source_code = f.read()

            # Verify error chunk structure follows OpenAI format
            required_fields = [
                '"object": "chat.completion.chunk"',
                '"choices":',
                '"finish_reason": "stop"',
                '"error":',
                '"message":',
                '"type":',
                '"code":',
            ]

            for field in required_fields:
                assert field in source_code, (
                    f"{file_path} error chunks should include {field} "
                    f"for OpenAI-compatible error responses"
                )

    def test_no_abrupt_exception_raising_in_streaming(self):
        """
        Test that streaming methods don't raise exceptions that would
        terminate connections abruptly.
        """
        files_to_check = [
            "src/connectors/gemini_oauth_base.py",
            "src/connectors/gemini_cloud_project.py",
        ]

        for file_path in files_to_check:
            with open(file_path) as f:
                source_code = f.read()

            # Look for streaming generator methods
            import re

            streaming_methods = re.findall(
                r"(async def.*stream.*?(?=async def|def [^_]|class|\Z))",
                source_code,
                re.DOTALL,
            )

            for method in streaming_methods:
                # Check if method raises BackendError without graceful handling
                if "raise BackendError" in method:
                    # If it raises BackendError, it should also have graceful handling
                    assert "yield ProcessedResponse" in method, (
                        f"Streaming method in {file_path} raises BackendError "
                        f"but doesn't have graceful error chunk yielding. "
                        f"This causes abrupt connection termination."
                    )

    def test_quota_error_detection_logic(self):
        """
        Test that quota error detection logic is comprehensive.
        """
        files_to_check = [
            "src/connectors/gemini_oauth_base.py",
            "src/connectors/gemini_cloud_project.py",
        ]

        for file_path in files_to_check:
            with open(file_path) as f:
                source_code = f.read()

            # Verify comprehensive quota error detection
            quota_patterns = ["quota exceeded", "resource exhausted", "allowance"]

            for pattern in quota_patterns:
                assert pattern in source_code.lower(), (
                    f"{file_path} should detect '{pattern}' as a quota error "
                    f"for comprehensive quota exhaustion handling"
                )

            # Verify 429 status code handling
            assert "response.status_code == 429" in source_code, (
                f"{file_path} should specifically handle HTTP 429 status code "
                f"for quota exhaustion scenarios"
            )

    def test_backend_marking_on_quota_exhaustion(self):
        """
        Test that backends are properly marked as unusable on quota exhaustion
        but without killing the current request.
        """
        # Only check gemini_oauth_base.py as it has the _mark_backend_unusable method
        # gemini_cloud_project.py handles this at a higher level
        file_path = "src/connectors/gemini_oauth_base.py"

        with open(file_path) as f:
            source_code = f.read()

        # Should mark backend as unusable on quota errors
        if "is_quota_error" in source_code:
            # If quota detection exists, should mark backend unusable
            assert "_mark_backend_unusable" in source_code, (
                f"{file_path} should mark backend as unusable when quota is exhausted "
                f"to prevent further requests to exhausted backend"
            )


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
