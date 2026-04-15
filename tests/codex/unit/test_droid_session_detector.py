"""TDD tests for Droid client detection.

These tests define the expected behavior of the DroidSessionDetector class
which identifies Factory Droid clients from request metadata.

Test isolation: All tests in this file are auto-marked with @pytest.mark.codex
by conftest.py and excluded from default pytest runs.
"""


class TestDroidSessionDetector:
    """TDD tests for Droid client detection."""

    def test_detect_droid_from_user_agent_factory_cli(self):
        """User-Agent containing 'factory-cli' should detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(headers={"User-Agent": "factory-cli/0.27.1"})
        assert result.is_droid is True
        assert result.detection_method == "user_agent"

    def test_detect_droid_from_user_agent_droid(self):
        """User-Agent containing 'droid' should detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(headers={"User-Agent": "Droid/1.0"})
        assert result.is_droid is True
        assert result.detection_method == "user_agent"

    def test_detect_droid_from_system_prompt(self):
        """System prompt mentioning 'Droid' should detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(
            messages=[
                {
                    "role": "system",
                    "content": "You are Droid, an AI software engineer...",
                }
            ]
        )
        assert result.is_droid is True
        assert result.detection_method == "system_prompt"

    def test_detect_droid_from_tool_names(self):
        """Presence of Droid-specific tools should detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        # Droid uses specific tool names like Read, LS, Execute, etc.
        droid_tools = [
            {"type": "function", "function": {"name": "Read"}},
            {"type": "function", "function": {"name": "LS"}},
            {"type": "function", "function": {"name": "Execute"}},
        ]
        result = detector.detect(tools=droid_tools)
        assert result.is_droid is True
        assert result.detection_method == "tool_names"

    def test_not_detect_non_droid_user_agent(self):
        """Non-Droid user agents should not detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(headers={"User-Agent": "cline/1.0"})
        assert result.is_droid is False

    def test_not_detect_non_droid_system_prompt(self):
        """Non-Droid system prompts should not detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(
            messages=[
                {
                    "role": "system",
                    "content": "You are Claude, an AI assistant...",
                }
            ]
        )
        assert result.is_droid is False

    def test_detect_with_no_input(self):
        """Empty input should not detect as Droid."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect()
        assert result.is_droid is False

    def test_detect_case_insensitive(self):
        """Detection should be case-insensitive."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(headers={"User-Agent": "FACTORY-CLI/0.27.1"})
        assert result.is_droid is True

    def test_detect_with_mixed_case_system_prompt(self):
        """Detection should handle mixed case in system prompt."""
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(
            messages=[
                {
                    "role": "system",
                    "content": "You are DROID, an AI software engineer...",
                }
            ]
        )
        assert result.is_droid is True

    def test_not_detect_similar_but_not_matching_user_agent(self):
        """User agents with similar substrings should not false-positive.

        For example, 'my_factory_client' should not match 'factory_cli'
        because token-based matching requires whole-token matches.
        """
        from src.connectors._openai_codex_droid_session_detector import (
            DroidSessionDetector,
        )

        detector = DroidSessionDetector()
        result = detector.detect(headers={"User-Agent": "my_factory_client/1.0"})
        assert result.is_droid is False
