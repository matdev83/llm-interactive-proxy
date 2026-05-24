"""Unit tests for FileModificationDetector."""

from __future__ import annotations

from src.services.test_execution_reminder.file_modification_detector import (
    FileModificationDetector,
)


class TestFileModificationDetector:
    """Test suite for FileModificationDetector class."""

    def test_basic_tool_name_detection(self) -> None:
        """Test detection of basic file modification tool names."""
        # All standard tool names should be detected
        assert FileModificationDetector.is_file_modification("write_file") is True
        assert FileModificationDetector.is_file_modification("replace_lines") is True
        assert FileModificationDetector.is_file_modification("replace_in_file") is True
        assert FileModificationDetector.is_file_modification("write_to_file") is True
        assert FileModificationDetector.is_file_modification("apply_diff") is True
        assert FileModificationDetector.is_file_modification("apply_patch") is True
        assert FileModificationDetector.is_file_modification("patch_file") is True
        assert FileModificationDetector.is_file_modification("str_replace") is True
        assert FileModificationDetector.is_file_modification("multiedit") is True
        assert FileModificationDetector.is_file_modification("insert_content") is True
        assert FileModificationDetector.is_file_modification("patch") is True

    def test_tool_name_with_slashes(self) -> None:
        """Test detection of tool names containing slashes."""
        # Tool names with slashes should be detected
        assert (
            FileModificationDetector.is_file_modification("fs/write_text_file") is True
        )

    def test_case_insensitive_matching(self) -> None:
        """Test that tool name matching is case-insensitive."""
        # Uppercase variations
        assert FileModificationDetector.is_file_modification("WRITE_FILE") is True
        assert FileModificationDetector.is_file_modification("REPLACE_LINES") is True
        assert FileModificationDetector.is_file_modification("STR_REPLACE") is True
        assert FileModificationDetector.is_file_modification("MULTIEDIT") is True

        # Mixed case variations
        assert FileModificationDetector.is_file_modification("Write_File") is True
        assert FileModificationDetector.is_file_modification("Replace_Lines") is True
        assert FileModificationDetector.is_file_modification("Str_Replace") is True
        assert FileModificationDetector.is_file_modification("MultiEdit") is True

        # All lowercase
        assert FileModificationDetector.is_file_modification("write_file") is True
        assert FileModificationDetector.is_file_modification("replace_lines") is True

    def test_normalization_with_underscores(self) -> None:
        """Test that underscores are normalized in tool names."""
        # Without underscores
        assert FileModificationDetector.is_file_modification("writefile") is True
        assert FileModificationDetector.is_file_modification("replacelines") is True
        assert FileModificationDetector.is_file_modification("strreplace") is True
        assert FileModificationDetector.is_file_modification("patchfile") is True
        assert FileModificationDetector.is_file_modification("fswrite") is True

        # With underscores (original format)
        assert FileModificationDetector.is_file_modification("write_file") is True
        assert FileModificationDetector.is_file_modification("replace_lines") is True
        assert FileModificationDetector.is_file_modification("str_replace") is True
        assert FileModificationDetector.is_file_modification("patch_file") is True
        assert FileModificationDetector.is_file_modification("fs_write") is True

    def test_normalization_with_slashes(self) -> None:
        """Test that slashes are normalized in tool names."""
        # With slashes
        assert (
            FileModificationDetector.is_file_modification("fs/write_text_file") is True
        )

        # Without slashes (normalized)
        assert FileModificationDetector.is_file_modification("fswritetextfile") is True

        # Mixed case without slashes
        assert FileModificationDetector.is_file_modification("FsWriteTextFile") is True

    def test_combined_normalization(self) -> None:
        """Test normalization with both underscores and slashes."""
        # Original format
        assert (
            FileModificationDetector.is_file_modification("fs/write_text_file") is True
        )

        # No underscores
        assert FileModificationDetector.is_file_modification("fs/writetextfile") is True

        # No slashes
        assert (
            FileModificationDetector.is_file_modification("fs_write_text_file") is True
        )

        # No underscores or slashes
        assert FileModificationDetector.is_file_modification("fswritetextfile") is True

        # Uppercase, no underscores or slashes
        assert FileModificationDetector.is_file_modification("FSWRITETEXTFILE") is True

    def test_non_modification_tool_rejection(self) -> None:
        """Test that non-modification tools are not detected."""
        # Read operations
        assert FileModificationDetector.is_file_modification("read_file") is False
        assert FileModificationDetector.is_file_modification("list_files") is False
        assert FileModificationDetector.is_file_modification("search_files") is False

        # Execution operations
        assert FileModificationDetector.is_file_modification("execute_command") is False
        assert FileModificationDetector.is_file_modification("run_tests") is False
        assert FileModificationDetector.is_file_modification("pytest") is False

        # Other operations
        assert FileModificationDetector.is_file_modification("task_complete") is False
        assert FileModificationDetector.is_file_modification("get_status") is False
        assert FileModificationDetector.is_file_modification("analyze_code") is False

    def test_empty_string_handling(self) -> None:
        """Test handling of empty string input."""
        assert FileModificationDetector.is_file_modification("") is False

    def test_none_handling(self) -> None:
        """Test handling of None input."""
        # None should be handled gracefully
        # The implementation checks "if not tool_name" which catches None
        assert FileModificationDetector.is_file_modification(None) is False  # type: ignore[arg-type]

    def test_whitespace_only_handling(self) -> None:
        """Test handling of whitespace-only strings."""
        assert FileModificationDetector.is_file_modification("   ") is False
        assert FileModificationDetector.is_file_modification("\t") is False
        assert FileModificationDetector.is_file_modification("\n") is False
        assert FileModificationDetector.is_file_modification("  \t\n  ") is False

    def test_partial_match_rejection(self) -> None:
        """Test that partial matches are not detected."""
        # These contain modification tool names but are not exact matches
        assert (
            FileModificationDetector.is_file_modification("write_file_backup") is False
        )
        assert (
            FileModificationDetector.is_file_modification("backup_write_file") is False
        )
        assert FileModificationDetector.is_file_modification("str_replace_all") is False
        assert (
            FileModificationDetector.is_file_modification("multi_str_replace") is False
        )

    def test_similar_but_different_names(self) -> None:
        """Test that similar but different tool names are not detected."""
        # These are similar to modification tools but not the same
        assert FileModificationDetector.is_file_modification("write_files") is False
        assert FileModificationDetector.is_file_modification("replace_line") is False
        assert FileModificationDetector.is_file_modification("patches") is False
        assert FileModificationDetector.is_file_modification("editing") is False

    def test_all_registered_tool_variants(self) -> None:
        """Test all tool name variants from FILE_MODIFICATION_TOOLS."""
        # Test each tool in the registry
        expected_tools = {
            "write_file",
            "replace_lines",
            "replace_in_file",
            "write_to_file",
            "apply_diff",
            "apply_patch",
            "patch_file",
            "str_replace",
            "multiedit",
            "fs/write_text_file",
            "insert_content",
            "patch",
            "patchfile",
            "strreplace",
            "fswrite",
            "fs_write",
        }

        for tool in expected_tools:
            assert (
                FileModificationDetector.is_file_modification(tool) is True
            ), f"Tool '{tool}' should be detected as file modification"

    def test_normalization_consistency(self) -> None:
        """Test that normalization is consistent across different formats."""
        # All these should be detected as the same tool (write_file)
        variants = [
            "write_file",
            "WRITE_FILE",
            "Write_File",
            "writefile",
            "WRITEFILE",
            "WriteFile",
        ]

        for variant in variants:
            assert (
                FileModificationDetector.is_file_modification(variant) is True
            ), f"Variant '{variant}' should be detected"

    def test_edge_case_special_characters(self) -> None:
        """Test handling of tool names with special characters."""
        # Tool names with special characters that aren't underscores or slashes
        assert FileModificationDetector.is_file_modification("write-file") is False
        assert FileModificationDetector.is_file_modification("write.file") is False
        assert FileModificationDetector.is_file_modification("write file") is False
        assert FileModificationDetector.is_file_modification("write@file") is False

    def test_very_long_tool_name(self) -> None:
        """Test handling of very long tool names."""
        long_name = "a" * 1000
        assert FileModificationDetector.is_file_modification(long_name) is False

    def test_unicode_characters(self) -> None:
        """Test handling of tool names with unicode characters."""
        # ASCII-only test names (no unicode emojis allowed per AGENTS.md)
        assert (
            FileModificationDetector.is_file_modification("write_file_unicode") is False
        )
        assert (
            FileModificationDetector.is_file_modification("non_english_chars") is False
        )
        assert FileModificationDetector.is_file_modification("ecrire_fichier") is False
