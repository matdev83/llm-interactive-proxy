"""Tests for DroidPathFixup.

Following TDD methodology: tests written after implementation.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from src.core.services.tool_call_reactor.fixups.droid_path_fixup import (
    DroidPathFixup,
)


class TestShouldApply:
    """Tests for should_apply activation logic."""

    def test_should_apply_for_droid_agent(self) -> None:
        """Test that fixup applies for droid agent."""
        fixup = DroidPathFixup()

        assert fixup.should_apply("droid-agent/1.0") is True
        assert fixup.should_apply("DROID-agent") is True
        assert fixup.should_apply("some-droid-client") is True

    def test_should_apply_for_factory_agent(self) -> None:
        """Test that fixup applies for factory agent."""
        fixup = DroidPathFixup()

        assert fixup.should_apply("factory-cli/1.0.0") is True
        assert fixup.should_apply("FACTORY-client") is True
        assert fixup.should_apply("some-factory-tool") is True

    def test_should_not_apply_for_other_agents(self) -> None:
        """Test that fixup does not apply for other agents."""
        fixup = DroidPathFixup()

        assert fixup.should_apply("other-agent/1.0") is False
        assert fixup.should_apply("claude-client") is False
        assert fixup.should_apply(None) is False
        assert fixup.should_apply("") is False


class TestPathExtraction:
    """Tests for path extraction from arguments."""

    def test_extract_path_from_file_path_key(self) -> None:
        """Test extracting path from file_path key."""
        fixup = DroidPathFixup()
        args = {"file_path": "relative/path", "other": "value"}

        path, key = fixup._extract_path(args)

        assert path == "relative/path"
        assert key == "file_path"

    def test_extract_path_from_path_key(self) -> None:
        """Test extracting path from path key."""
        fixup = DroidPathFixup()
        args = {"path": "relative/path", "other": "value"}

        path, key = fixup._extract_path(args)

        assert path == "relative/path"
        assert key == "path"

    def test_extract_path_checks_multiple_keys(self) -> None:
        """Test that extraction checks multiple path keys."""
        fixup = DroidPathFixup()
        args = {"other": "value", "AbsolutePath": "relative/path"}

        path, key = fixup._extract_path(args)

        assert path == "relative/path"
        assert key == "AbsolutePath"

    def test_extract_path_returns_none_when_not_found(self) -> None:
        """Test that extraction returns None when no path found."""
        fixup = DroidPathFixup()
        args = {"other": "value", "not_a_path": 123}

        path, key = fixup._extract_path(args)

        assert path is None
        assert key is None

    def test_extract_path_handles_empty_string(self) -> None:
        """Test that extraction skips empty strings."""
        fixup = DroidPathFixup()
        args = {"file_path": "", "path": "   "}

        path, key = fixup._extract_path(args)

        assert path is None
        assert key is None


class TestNeedsFix:
    """Tests for needs_fix logic."""

    def test_needs_fix_for_relative_path(self) -> None:
        """Test that relative paths need fixing."""
        fixup = DroidPathFixup()

        assert fixup._needs_fix("relative/path") is True
        assert fixup._needs_fix("./relative/path") is True
        assert fixup._needs_fix("../relative/path") is True

    def test_needs_fix_skips_windows_drive_path(self) -> None:
        """Test that Windows drive paths don't need fixing."""
        fixup = DroidPathFixup()

        assert fixup._needs_fix("C:\\absolute\\path") is False
        assert fixup._needs_fix("D:/absolute/path") is False
        assert fixup._needs_fix("c:relative") is False

    def test_needs_fix_skips_unc_path(self) -> None:
        """Test that UNC paths don't need fixing."""
        fixup = DroidPathFixup()

        assert fixup._needs_fix("\\\\server\\share\\path") is False
        assert fixup._needs_fix("\\\\server\\share") is False


class TestFixPath:
    """Tests for path fixing logic."""

    def test_fix_path_makes_absolute(self) -> None:
        """Test that fix_path makes relative paths absolute."""
        fixup = DroidPathFixup()
        relative_path = "relative/path"

        fixed = fixup._fix_path(relative_path)

        assert os.path.isabs(fixed)
        assert "relative" in fixed
        assert "path" in fixed

    def test_fix_path_strips_leading_separators(self) -> None:
        """Test that fix_path strips leading separators."""
        fixup = DroidPathFixup()
        path_with_separator = "/relative/path"

        fixed = fixup._fix_path(path_with_separator)

        assert os.path.isabs(fixed)
        # Should not start with double separators
        assert not fixed.startswith("//")

    @patch("os.getcwd")
    def test_fix_path_joins_with_cwd(self, mock_cwd: pytest.Mock) -> None:
        """Test that fix_path joins with current working directory."""
        # Use platform-appropriate path to avoid traversal detection (drive mismatch)
        mock_cwd.return_value = "C:\\test\\cwd" if os.name == "nt" else "/test/cwd"

        fixup = DroidPathFixup()
        relative_path = "relative/path"

        fixed = fixup._fix_path(relative_path)

        assert os.path.isabs(fixed)
        # Should contain cwd components
        assert "test" in fixed or "cwd" in fixed

    def test_fix_path_detects_traversal(self) -> None:
        """Test that fix_path returns original path if traversal detected."""
        fixup = DroidPathFixup()
        # Traverse out of CWD
        relative_path = "../../../../../../../../../../../../../windows/system32"

        fixed = fixup._fix_path(relative_path)

        # Should return original path because it's outside CWD
        assert fixed == relative_path


class TestApply:
    """Tests for apply method."""

    def test_apply_fixes_relative_path_for_droid(self) -> None:
        """Test that apply fixes relative paths for droid agent."""
        fixup = DroidPathFixup()
        args = {"file_path": "relative/path", "other": "value"}

        fixed_args, was_modified = fixup.apply(args, "droid-agent")

        assert was_modified is True
        assert "file_path" in fixed_args
        assert os.path.isabs(fixed_args["file_path"])
        assert fixed_args["other"] == "value"

    def test_apply_skips_for_non_droid_agent(self) -> None:
        """Test that apply skips for non-droid agents."""
        fixup = DroidPathFixup()
        args = {"file_path": "relative/path"}

        fixed_args, was_modified = fixup.apply(args, "other-agent")

        assert was_modified is False
        assert fixed_args == args

    def test_apply_skips_absolute_paths(self) -> None:
        """Test that apply skips already absolute paths."""
        fixup = DroidPathFixup()
        args = {"file_path": "C:\\absolute\\path"}

        fixed_args, was_modified = fixup.apply(args, "droid-agent")

        assert was_modified is False
        assert fixed_args["file_path"] == "C:\\absolute\\path"

    def test_apply_sets_default_key_when_no_path_key_found(self) -> None:
        """Test that apply sets file_path as default when no path key found."""
        fixup = DroidPathFixup()
        # This shouldn't happen in practice, but test the behavior
        args = {"other": "value"}

        fixed_args, was_modified = fixup.apply(args, "droid-agent")

        # Should not modify if no path found
        assert was_modified is False

    def test_apply_preserves_other_keys(self) -> None:
        """Test that apply preserves non-path keys."""
        fixup = DroidPathFixup()
        args = {
            "file_path": "relative/path",
            "other_key": "other_value",
            "nested": {"inner": "value"},
        }

        fixed_args, was_modified = fixup.apply(args, "droid-agent")

        assert was_modified is True
        assert fixed_args["other_key"] == "other_value"
        assert fixed_args["nested"] == {"inner": "value"}
