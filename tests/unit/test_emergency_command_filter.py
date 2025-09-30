"""
Tests for the emergency command filter functionality.
"""

from src.security import ProxyCommandFilter


class TestProxyCommandFilter:
    """Test the ProxyCommandFilter emergency filter."""

    def test_filter_initialization(self) -> None:
        """Test filter initialization with different prefixes."""
        filter1 = ProxyCommandFilter("!/")
        assert filter1.command_prefix == "!/"

        filter2 = ProxyCommandFilter("##")
        assert filter2.command_prefix == "##"

    def test_basic_command_detection_and_removal(self) -> None:
        """Test basic command detection and removal."""
        pcf_filter = ProxyCommandFilter("!/")

        # Test single command
        result = pcf_filter.filter_commands("Hello !/world")
        assert result == "Hello "

        # Test multiple commands
        result = pcf_filter.filter_commands("Start !/middle end")
        assert result == "Start  end"

    def test_command_only_text(self) -> None:
        """Test filtering text that contains only commands."""
        pcf_filter = ProxyCommandFilter("!/")

        result = pcf_filter.filter_commands("!/hello")
        assert result == "(command_removed)"

        result = pcf_filter.filter_commands("    !/hello")
        assert result == "(command_removed)"

    def test_no_commands_present(self) -> None:
        """Test that normal text without commands is unchanged."""
        pcf_filter = ProxyCommandFilter("!/")

        text = "This is normal text without any commands"
        result = pcf_filter.filter_commands(text)
        assert result == text

        text = "Text with ! but no commands"
        result = pcf_filter.filter_commands(text)
        assert result == text

    def test_different_command_prefixes(self) -> None:
        """Test filtering with different command prefixes."""
        pcf_filter = ProxyCommandFilter("##")

        # Should filter ## commands but not !/ commands
        text = "Hello ##set(model=test) and !/world"
        result = pcf_filter.filter_commands(text)
        assert result == "Hello  and !/world"

    def test_prefix_update(self) -> None:
        """Test updating the command prefix."""
        pcf_filter = ProxyCommandFilter("!/")

        # Initially filters !/ commands
        result = pcf_filter.filter_commands("Hello !/world")
        assert result == "Hello "

        # Update prefix
        pcf_filter.set_command_prefix("##")

        # Now filters ## commands but not !/ commands
        result = pcf_filter.filter_commands("Hello !/world and ##help")
        assert result == "Hello !/world and "

    def test_edge_cases(self) -> None:
        """Test edge cases like empty strings and whitespace."""
        pcf_filter = ProxyCommandFilter("!/")

        # Empty string
        assert pcf_filter.filter_commands("") == ""

        # Only whitespace
        result = pcf_filter.filter_commands("   ")
        assert result == "   "

        # Commands with extra whitespace
        result = pcf_filter.filter_commands("    !/hello")
        assert result == "(command_removed)"

    def test_complex_command_patterns(self) -> None:
        """Test various command patterns."""
        pcf_filter = ProxyCommandFilter("!/")

        test_cases = [
            ("!/hello", "(command_removed)"),
            ("!/model(gemini-2.5-pro)", "(command_removed)"),
            ("text !/hello and more", "text  and more"),
            (" !/hello", "(command_removed)"),
            ("!/hello ", "(command_removed)"),
            ("  !/hello  ", "(command_removed)"),
            ("!/model(gemini-2.5-pro) !/hello", "(command_removed)"),
            ("!/model(gemini-2.5-pro)!/hello", "(command_removed)"),
            ("!/model(gemini-2.5-pro)middle!/hello", "middle"),
            ("prefix!/model(gemini-2.5-pro)suffix", "prefixsuffix"),
            ("!/model(gemini-2.5-pro) suffix", " suffix"),
            ("prefix !/model(gemini-2.5-pro)", "prefix "),
            ("!/model(gemini-2.5-pro)", "(command_removed)"),
        ]

        for input_text, expected_output in test_cases:
            result = pcf_filter.filter_commands(input_text)
            assert result == expected_output, f"Failed for: '{input_text}'"
