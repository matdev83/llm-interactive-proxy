"""Unit tests for VTC (Virtual Tool Calling) client detection."""

from src.core.services.vtc_detection import detect_vtc_client


class TestDetectVtcClient:
    """Tests for the detect_vtc_client function."""

    def test_detects_cline_exact(self) -> None:
        """Test detection of exact 'cline' match."""
        assert detect_vtc_client("cline", ["cline", "kilo", "roo"]) is True

    def test_detects_cline_case_insensitive(self) -> None:
        """Test case-insensitive detection of Cline variants."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("Cline", patterns) is True
        assert detect_vtc_client("CLINE", patterns) is True
        assert detect_vtc_client("cLiNe", patterns) is True

    def test_detects_cline_in_user_agent_string(self) -> None:
        """Test detection of Cline within a full User-Agent string."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("Cline/1.0.0", patterns) is True
        assert detect_vtc_client("vscode-cline/2.5.1", patterns) is True
        assert detect_vtc_client("Mozilla/5.0 Cline-Agent", patterns) is True

    def test_detects_kilocode(self) -> None:
        """Test detection of KiloCode agent."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("KiloCode/1.0", patterns) is True
        assert detect_vtc_client("kilocode-agent", patterns) is True
        assert detect_vtc_client("KILOCODE", patterns) is True

    def test_detects_roocode(self) -> None:
        """Test detection of RooCode agent."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("RooCode/0.5", patterns) is True
        assert detect_vtc_client("roo-agent/1.2.3", patterns) is True
        assert detect_vtc_client("ROO-Extension", patterns) is True

    def test_does_not_detect_non_vtc_agents(self) -> None:
        """Test that non-VTC agents are not detected."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("cursor/1.0", patterns) is False
        assert detect_vtc_client("vscode/1.85", patterns) is False
        assert detect_vtc_client("Mozilla/5.0", patterns) is False
        assert detect_vtc_client("factory-cli/0.27.4", patterns) is False
        assert detect_vtc_client("anthropic-sdk/1.0", patterns) is False

    def test_returns_false_for_none_agent(self) -> None:
        """Test that None agent returns False."""
        assert detect_vtc_client(None, ["cline", "kilo", "roo"]) is False

    def test_returns_false_for_empty_agent(self) -> None:
        """Test that empty string agent returns False."""
        assert detect_vtc_client("", ["cline", "kilo", "roo"]) is False

    def test_returns_false_for_empty_patterns(self) -> None:
        """Test that empty patterns list returns False."""
        assert detect_vtc_client("Cline/1.0", []) is False

    def test_returns_false_for_none_patterns_equivalent(self) -> None:
        """Test behavior with empty patterns as if None."""
        # Empty list is falsy in Python
        assert detect_vtc_client("Cline/1.0", []) is False

    def test_custom_patterns(self) -> None:
        """Test with custom pattern list."""
        custom_patterns = ["custom-agent", "my-vtc"]
        assert detect_vtc_client("custom-agent/1.0", custom_patterns) is True
        assert detect_vtc_client("my-vtc-extension", custom_patterns) is True
        assert detect_vtc_client("Cline/1.0", custom_patterns) is False

    def test_pattern_case_insensitivity(self) -> None:
        """Test that patterns themselves are matched case-insensitively."""
        # Even if pattern is uppercase, it should match lowercase agent
        assert detect_vtc_client("cline/1.0", ["CLINE"]) is True
        assert detect_vtc_client("CLINE/1.0", ["cline"]) is True

    def test_partial_match(self) -> None:
        """Test that partial matches work (substring matching)."""
        patterns = ["cline"]
        # 'cline' is a substring of these
        assert detect_vtc_client("decline-bot", patterns) is True  # Contains 'cline'
        assert detect_vtc_client("incline", patterns) is True  # Contains 'cline'

    def test_whitespace_in_agent(self) -> None:
        """Test agents with whitespace."""
        patterns = ["cline", "kilo", "roo"]
        assert detect_vtc_client("Cline Agent", patterns) is True
        assert detect_vtc_client("  Cline  ", patterns) is True

    def test_returns_false_for_non_string_agent(self) -> None:
        """Test that non-string agents return False (handles mock objects)."""
        patterns = ["cline", "kilo", "roo"]
        # Test with various non-string types
        assert detect_vtc_client(123, patterns) is False  # type: ignore[arg-type]
        assert detect_vtc_client(["cline"], patterns) is False  # type: ignore[arg-type]
        assert detect_vtc_client({"agent": "cline"}, patterns) is False  # type: ignore[arg-type]

    def test_returns_false_for_non_list_patterns(self) -> None:
        """Test that non-list patterns return False."""
        # Test with various non-list types
        assert detect_vtc_client("Cline/1.0", "cline") is False  # type: ignore[arg-type]
        assert detect_vtc_client("Cline/1.0", {"pattern": "cline"}) is False  # type: ignore[arg-type]
