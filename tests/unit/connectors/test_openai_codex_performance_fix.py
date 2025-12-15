"""
Test performance optimization in OpenAI Codex connector.

This test ensures that token refresh doesn't trigger unnecessary payload rebuilding
that was causing slow performance and rapid quota consumption.
"""

import re

import pytest


class TestOpenAICodexPerformanceOptimization:
    """Test suite for OpenAI Codex performance optimization."""

    def test_no_unnecessary_payload_rebuilding_on_token_refresh(self):
        """
        Test that token refresh doesn't rebuild payload unnecessarily.

        This was causing slow performance and rapid quota consumption.
        """
        with open("src/connectors/openai_codex.py") as f:
            source_code = f.read()

        # Look for the retry logic section
        retry_pattern = r"for attempt in range.*?except HTTPException.*?if exc\.status_code == 401.*?continue"
        retry_sections = re.findall(retry_pattern, source_code, re.DOTALL)

        assert len(retry_sections) > 0, "Should have retry logic for token refresh"

        for section in retry_sections:
            # Should NOT rebuild payload on token refresh
            assert "_build_codex_payload" not in section, (
                "Token refresh should not rebuild payload - this causes "
                "performance issues and potential quota waste"
            )

            # Should NOT generate new conversation_id on retry
            assert (
                "conversation_id = " not in section or "uuid.uuid4()" not in section
            ), (
                "Token refresh should not generate new conversation_id - this breaks "
                "session continuity and may cause double billing"
            )

            # Should NOT rebuild headers on retry
            assert "_build_codex_headers" not in section, (
                "Token refresh should not rebuild headers - this is unnecessary "
                "overhead and may cause session fragmentation"
            )

    def test_efficient_retry_pattern(self):
        """
        Test that retry logic is efficient and doesn't waste resources.
        """
        with open("src/connectors/openai_codex.py") as f:
            source_code = f.read()

        # Should have token refresh capability
        assert (
            "_refresh_access_token" in source_code
        ), "Should have token refresh capability for handling expired tokens"

        # Should have retry logic
        assert (
            "for attempt in range" in source_code
        ), "Should have retry logic for handling token expiration"

        # Should handle 401 errors specifically
        assert (
            "exc.status_code == 401" in source_code
        ), "Should specifically handle 401 Unauthorized errors for token refresh"

    def test_session_continuity_preservation(self):
        """
        Test that session continuity is preserved during token refresh.
        """
        with open("src/connectors/openai_codex.py") as f:
            source_code = f.read()

        # Look for conversation_id generation
        conversation_id_pattern = r"conversation_id = str\(uuid\.uuid4\(\)\)"
        conversation_id_matches = re.findall(conversation_id_pattern, source_code)

        # Should only generate conversation_id once per request, not on retries
        assert len(conversation_id_matches) <= 2, (
            f"Found {len(conversation_id_matches)} conversation_id generations. "
            f"Should be minimal to avoid session fragmentation. "
            f"Multiple generations indicate unnecessary rebuilding on retries."
        )

    def test_no_double_processing_patterns(self):
        """
        Test that there are no patterns that could cause double processing.
        """
        with open("src/connectors/openai_codex.py") as f:
            source_code = f.read()

        # Look for retry sections
        retry_pattern = r"for attempt in range.*?except.*?continue"
        retry_sections = re.findall(retry_pattern, source_code, re.DOTALL)

        for section in retry_sections:
            # Should not have expensive operations in retry loop
            expensive_operations = [
                "_build_codex_payload",
                "processed_messages",
                "uuid.uuid4()",
                "_build_codex_headers",
            ]

            for operation in expensive_operations:
                assert operation not in section, (
                    f"Retry logic should not contain expensive operation '{operation}' "
                    f"as this causes performance issues and potential quota waste"
                )

    def test_quota_efficiency_indicators(self):
        """
        Test for indicators of quota-efficient implementation.
        """
        with open("src/connectors/openai_codex.py") as f:
            source_code = f.read()

        # Should have comments indicating the fix
        efficiency_indicators = [
            "Only refresh token",
            "reuse same payload",
            "maintain session continuity",
            "No need to rebuild",
        ]

        found_indicators = 0
        for indicator in efficiency_indicators:
            if indicator in source_code:
                found_indicators += 1

        assert found_indicators >= 2, (
            f"Should have comments indicating efficiency improvements. "
            f"Found {found_indicators} out of {len(efficiency_indicators)} indicators. "
            f"This suggests the performance fix is properly documented."
        )


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
