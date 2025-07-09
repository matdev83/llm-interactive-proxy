"""
Tests for the emergency command filter functionality.
"""
import pytest
from src.security import ProxyCommandFilter


class TestProxyCommandFilter:
    """Test the ProxyCommandFilter emergency filter."""

    def test_filter_initialization(self):
        """Test filter initialization with different prefixes."""
        filter1 = ProxyCommandFilter("!/")
        assert filter1.command_prefix == "!/"
        
        filter2 = ProxyCommandFilter("##")
        assert filter2.command_prefix == "##"

    def test_basic_command_detection_and_removal(self):
        """Test basic command detection and removal."""
        filter = ProxyCommandFilter("!/")
        
        # Test single command
        result = filter.filter_commands("Hello !/set(model=gpt-4) world")
        assert "!/set" not in result
        assert "Hello" in result
        assert "world" in result
        
        # Test multiple commands
        result = filter.filter_commands("Start !/help middle !/unset(model) end")
        assert "!/help" not in result
        assert "!/unset" not in result
        assert "Start" in result
        assert "middle" in result
        assert "end" in result

    def test_command_only_text(self):
        """Test filtering text that contains only commands."""
        filter = ProxyCommandFilter("!/")
        
        result = filter.filter_commands("!/oneoff(gemini/gemini-pro)")
        assert result.strip() == ""
        
        result = filter.filter_commands("!/help")
        assert result.strip() == ""

    def test_no_commands_present(self):
        """Test that normal text without commands is unchanged."""
        filter = ProxyCommandFilter("!/")
        
        text = "This is normal text without any commands"
        result = filter.filter_commands(text)
        assert result == text
        
        text = "Text with ! but no commands"
        result = filter.filter_commands(text)
        assert result == text

    def test_different_command_prefixes(self):
        """Test filtering with different command prefixes."""
        filter = ProxyCommandFilter("##")
        
        # Should filter ## commands but not !/ commands
        text = "Hello ##set(model=test) and !/set(model=old) world"
        result = filter.filter_commands(text)
        assert "##set" not in result
        assert "!/set(model=old)" in result  # Should remain
        assert "Hello" in result
        assert "world" in result

    def test_prefix_update(self):
        """Test updating the command prefix."""
        filter = ProxyCommandFilter("!/")
        
        # Initially filters !/ commands
        result = filter.filter_commands("Hello !/set(test)")
        assert "!/set" not in result
        
        # Update prefix
        filter.set_command_prefix("##")
        
        # Now filters ## commands but not !/ commands
        result = filter.filter_commands("Hello !/set(test) and ##help")
        assert "!/set(test)" in result  # Should remain
        assert "##help" not in result   # Should be filtered

    def test_edge_cases(self):
        """Test edge cases like empty strings and whitespace."""
        filter = ProxyCommandFilter("!/")
        
        # Empty string
        assert filter.filter_commands("") == ""
        
        # Only whitespace
        result = filter.filter_commands("   ")
        assert result == "   "
        
        # Commands with extra whitespace
        result = filter.filter_commands("  !/set(model=test)  !/help  ")
        assert "!/set" not in result
        assert "!/help" not in result

    def test_complex_command_patterns(self):
        """Test various command patterns."""
        filter = ProxyCommandFilter("!/")
        
        test_cases = [
            ("!/oneoff(backend/model)", ""),
            ("!/one-off(backend/model)", ""),
            ("!/set(model=gpt-4)", ""),
            ("!/unset(model)", ""),
            ("!/help", ""),
            ("!/hello", ""),
            ("!/route-list()", ""),
            ("!/route-append(name=test,backend/model)", ""),
        ]
        
        for input_text, expected_empty in test_cases:
            result = filter.filter_commands(input_text)
            assert result.strip() == expected_empty, f"Failed for: {input_text}"