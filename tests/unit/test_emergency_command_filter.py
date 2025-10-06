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

    def test_end_of_message_command_filtering(self) -> None:
        """Test the end-of-message-only command filtering."""
        pcf_filter = ProxyCommandFilter("!/")

        # Test cases where command is at end - should be filtered
        end_command_cases = [
            ("Hello !/world", "Hello "),
            ("Start !/middle end", "Start !/middle end"),  # Not at end
            ("!/hello", "(command_removed)"),
            ("Some text !/command", "Some text "),
            ("!/model(gpt-4)", "(command_removed)"),
            # Note: "!/" alone doesn't match our pattern - need command name
        ]

        for input_text, expected_output in end_command_cases:
            result = pcf_filter.filter_end_of_message_commands_only(input_text)
            assert result == expected_output, f"Failed end-of-message filtering for: '{input_text}'"

    def test_middle_commands_not_filtered_with_end_only_method(self) -> None:
        """Test that commands in the middle are not filtered with end-only method."""
        pcf_filter = ProxyCommandFilter("!/")

        # Commands in middle should NOT be filtered with end-only method
        middle_command_cases = [
            "Hello !/world there",
            "Start !/middle end",
            "The !/command is here",
            "Text !/with more !/commands after",  # Last command not at end
        ]

        for input_text in middle_command_cases:
            result = pcf_filter.filter_end_of_message_commands_only(input_text)
            assert result == input_text, f"Should not filter middle command in: '{input_text}'"

    def test_strict_command_filtering(self) -> None:
        """Test the strict command filtering (last non-blank line only)."""
        pcf_filter = ProxyCommandFilter("!/")

        # Test cases where command is on last non-blank line - should be filtered
        strict_command_cases = [
            ("Hello world\n!/help", "Hello world\n"),  # Command on last line
            ("Some context\n!/model(gpt-4)\n", "Some context\n\n"),  # Command on last non-blank line (newline preserved)
            ("!/backend(openai)", "(command_removed)"),  # Single line with command
            ("Text before\n!/command", "Text before\n"),  # Command on last line
            ("First line\nSecond line\n!/backend(openai)", "First line\nSecond line\n"),  # Multi-line with command at end
        ]

        for input_text, expected_output in strict_command_cases:
            result = pcf_filter.filter_commands_with_strict_mode(input_text)
            assert result == expected_output, f"Failed strict filtering for: '{input_text}'"

    def test_strict_mode_commands_not_filtered(self) -> None:
        """Test that commands not on last non-blank line are not filtered in strict mode."""
        pcf_filter = ProxyCommandFilter("!/")

        # Commands not on last non-blank line should NOT be filtered in strict mode
        non_strict_command_cases = [
            "Hello !/world there\nAnd more context",  # Command in middle, text on last line
            "Start !/middle end\nWith context after",  # Command not at end
            "The !/command is here\nAnd continues",  # Command in middle
            "First line\n!/command\nMore text after",  # Command not on last line
            "!/first\n!/second\nSome other text",  # Commands not on last line
        ]

        for input_text in non_strict_command_cases:
            result = pcf_filter.filter_commands_with_strict_mode(input_text)
            assert result == input_text, f"Should not filter non-last-line command in strict mode: '{input_text}'"

    def test_strict_mode_edge_cases(self) -> None:
        """Test edge cases for strict command filtering."""
        pcf_filter = ProxyCommandFilter("!/")

        # Edge cases
        edge_cases = [
            ("!/command\n\n\n", "(command_removed)"),  # Command with trailing blank lines
            ("\n\n!/command", "(command_removed)"),  # Command with leading blank lines
            ("   \n!/command\n   ", "(command_removed)"),  # Command with whitespace lines
            ("", ""),  # Empty string
            ("   ", "   "),  # Only whitespace
            ("No commands here", "No commands here"),  # No commands
        ]

        for input_text, expected_output in edge_cases:
            result = pcf_filter.filter_commands_with_strict_mode(input_text)
            assert result == expected_output, f"Failed edge case for: '{input_text}'"
