"""
Test performance optimization in OpenAI Codex connector.

This test ensures that token refresh doesn't trigger unnecessary payload rebuilding
that was causing slow performance and rapid quota consumption.
"""

import re
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONNECTOR_PATH = _PROJECT_ROOT / "src" / "connectors" / "_openai_codex_connector.py"
_EXECUTOR_PATH = _PROJECT_ROOT / "src" / "connectors" / "openai_codex" / "executor.py"

_CONNECTOR_CODE = _CONNECTOR_PATH.read_text() if _CONNECTOR_PATH.exists() else ""
_EXECUTOR_CODE = _EXECUTOR_PATH.read_text() if _EXECUTOR_PATH.exists() else ""


@pytest.fixture(autouse=True)
def _configure_logging_for_tests() -> None:
    """Override the unit-level autouse fixture to skip expensive logging setup.

    This test performs static source-code analysis only; logging setup
    adds ~1.2s of unnecessary overhead.
    """


class TestOpenAICodexPerformanceOptimization:
    """Test suite for OpenAI Codex performance optimization."""

    def test_no_unnecessary_payload_rebuilding_on_token_refresh(self):
        """
        Test that token refresh doesn't rebuild payload unnecessarily.

        This was causing slow performance and rapid quota consumption.
        After refactoring, retry logic is in executor.py, not connector.
        """
        connector_code = _CONNECTOR_CODE
        # Retry logic should not be in connector anymore
        retry_pattern = r"for attempt in range.*?except HTTPException.*?if exc\.status_code == 401.*?continue"
        retry_sections = re.findall(retry_pattern, connector_code, re.DOTALL)
        assert (
            len(retry_sections) == 0
        ), "Retry logic should not be in connector - it has been moved to executor.py"

        executor_code = _EXECUTOR_CODE

        # Should have retry logic in executor
        assert (
            "exc.status_code == 401" in executor_code
        ), "Retry logic for 401 errors should be in executor.py"

        # Check that executor retry logic doesn't rebuild payload unnecessarily
        retry_sections_executor = re.findall(
            r"if exc\.status_code == 401.*?attempts_used", executor_code, re.DOTALL
        )
        for section in retry_sections_executor:
            # Should NOT rebuild payload on token refresh
            assert "_build_codex_payload" not in section, (
                "Token refresh should not rebuild payload - this causes "
                "performance issues and potential quota waste"
            )

    def test_efficient_retry_pattern(self):
        """
        Test that retry logic is efficient and doesn't waste resources.
        After refactoring, retry logic is in executor.py.
        """
        connector_code = _CONNECTOR_CODE
        assert (
            "for attempt in range" not in connector_code
        ), "Retry logic should not be in connector - moved to executor.py"

        executor_code = _EXECUTOR_CODE

        # Should have retry logic in executor
        assert (
            "max_retries" in executor_code
        ), "Should have retry configuration in executor.py"

        # Should handle 401 errors specifically
        assert (
            "exc.status_code == 401" in executor_code
        ), "Should specifically handle 401 Unauthorized errors for token refresh in executor.py"

    def test_session_continuity_preservation(self):
        """
        Test that session continuity is preserved during token refresh.
        After refactoring, retry logic is in executor.py, not connector.
        """
        source_code = _EXECUTOR_CODE

        # Executor should derive conversation_id from payload, not generate it
        # Look for conversation_id assignment from payload (not UUID generation)
        conversation_id_from_payload = (
            "conversation_id = payload.prompt_cache_key or context.session_id"
        )
        assert (
            conversation_id_from_payload in source_code
            or "conversation_id = payload.prompt_cache_key" in source_code
        ), "Executor should use conversation_id from payload/context, not generate new ones"

        # Should NOT generate UUIDs for conversation_id in retry logic
        # Check retry sections don't regenerate conversation_id
        retry_sections = re.findall(
            r"if.*401.*?conversation_id.*?uuid", source_code, re.DOTALL | re.IGNORECASE
        )
        assert (
            len(retry_sections) == 0
        ), "Retry logic should not regenerate conversation_id - this causes session fragmentation"

    def test_no_double_processing_patterns(self):
        """
        Test that there are no patterns that could cause double processing.
        After refactoring, retry logic is in executor.py.
        """
        source_code = _EXECUTOR_CODE

        # Look for retry sections (executor uses while True with attempts_used, not for attempt in range)
        retry_pattern = r"while True.*?if.*401.*?attempts_used"
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
        After refactoring, retry logic is in executor.py.
        """
        executor_code = _EXECUTOR_CODE
        # Should have comments indicating the fix in executor
        efficiency_indicators = [
            "retry",
            "refresh",
            "payload",
            "session",
        ]

        found_indicators = 0
        for indicator in efficiency_indicators:
            if indicator.lower() in executor_code.lower():
                found_indicators += 1

        # Executor should have retry logic (at least 2 indicators)
        assert found_indicators >= 2, (
            f"Executor should have retry and efficiency logic. "
            f"Found {found_indicators} out of {len(efficiency_indicators)} indicators."
        )

        connector_code = _CONNECTOR_CODE
        assert (
            "for attempt in range" not in connector_code
        ), "Connector should not have retry logic - it's been moved to executor"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v"])
