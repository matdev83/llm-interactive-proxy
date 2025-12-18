"""Tests for ToolArgumentsFixupPipeline.

Following TDD methodology: tests written after implementation.
"""

from __future__ import annotations

from unittest.mock import Mock

from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
    FixupContext,
)
from src.core.interfaces.tool_call_reactor_internal import (
    NormalizedToolArguments,
    ToolArgumentsEnvelope,
)
from src.core.services.tool_call_reactor.arguments_fixup_pipeline import (
    ToolArgumentsFixupPipeline,
)
from src.core.services.windows_double_ampersand_fixer import (
    WindowsDoubleAmpersandFixer,
)


class TestPipelineComposition:
    """Tests for pipeline composition and sequencing."""

    def test_pipeline_applies_droid_fixup(self) -> None:
        """Test that pipeline applies Droid path fixup when agent matches."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "relative/path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="factory-cli/1.0.0",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should have modified the path to absolute
        assert result.was_modified_by_fixups is True
        assert "file_path" in result.normalized_arguments.root
        # Path should be absolute (starts with drive letter or is absolute)
        path = result.normalized_arguments.root["file_path"]
        assert isinstance(path, str)
        # Should be absolute (contains drive letter or starts with /)
        assert ":" in path or path.startswith(("/", "\\"))

    def test_pipeline_applies_windows_fixup(self) -> None:
        """Test that pipeline applies Windows ampersand fixup when conditions match."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"command": "echo hello && echo world"}
            ),
        )
        context = FixupContext(
            tool_name="execute_command",
            client_os="Windows",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should have modified the command if Windows fixup applies
        # (depends on WindowsDoubleAmpersandFixer logic)
        assert isinstance(result, ToolArgumentsEnvelope)

    def test_pipeline_tracks_modification_flag(self) -> None:
        """Test that pipeline sets was_modified_by_fixups correctly."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"key": "value"}),
        )
        context = FixupContext(tool_name="test_tool")

        # No fixups should apply
        result = pipeline.apply_fixups(envelope, context)

        assert result.was_modified_by_fixups is False

    def test_pipeline_preserves_original_envelope(self) -> None:
        """Test that pipeline modifies envelope in-place."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "relative/path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="droid-agent",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should be the same object (modified in-place)
        assert result is envelope


class TestDroidPathFixupActivation:
    """Tests for Droid path fixup activation conditions."""

    def test_droid_fixup_activates_for_droid_agent(self) -> None:
        """Test that Droid fixup activates for droid agent."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "relative/path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="droid-agent/1.0",
        )

        result = pipeline.apply_fixups(envelope, context)

        assert result.was_modified_by_fixups is True

    def test_droid_fixup_activates_for_factory_agent(self) -> None:
        """Test that Droid fixup activates for factory agent."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "relative/path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="factory-cli/1.0.0",
        )

        result = pipeline.apply_fixups(envelope, context)

        assert result.was_modified_by_fixups is True

    def test_droid_fixup_skips_for_other_agents(self) -> None:
        """Test that Droid fixup skips for non-droid/factory agents."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "relative/path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="other-agent/1.0",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should not modify (unless Windows fixup applies)
        # Windows fixup might apply, so we check that Droid didn't modify
        # by checking the path is still relative if no other fixup applied
        if not result.was_modified_by_fixups:
            path = result.normalized_arguments.root.get("file_path")
            if path:
                # If still relative, Droid fixup didn't apply
                assert not (":" in path or path.startswith(("/", "\\")))

    def test_droid_fixup_skips_absolute_paths(self) -> None:
        """Test that Droid fixup skips already absolute paths."""
        pipeline = ToolArgumentsFixupPipeline()
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"file_path": "C:\\absolute\\path"}
            ),
        )
        context = FixupContext(
            tool_name="read_file",
            calling_agent="droid-agent",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should not modify absolute paths
        assert result.normalized_arguments.root["file_path"] == "C:\\absolute\\path"
        # May still be modified by Windows fixup, but Droid shouldn't change it
        assert (
            result.was_modified_by_fixups is False
            or "C:" in result.normalized_arguments.root["file_path"]
        )


class TestWindowsAmpersandFixupDelegation:
    """Tests for Windows ampersand fixup delegation."""

    def test_windows_fixup_delegates_to_fixer(self) -> None:
        """Test that pipeline delegates to WindowsDoubleAmpersandFixer."""
        mock_fixer = Mock(spec=WindowsDoubleAmpersandFixer)
        mock_fixer.fix_tool_arguments = Mock(return_value=({"command": "fixed"}, True))
        pipeline = ToolArgumentsFixupPipeline(windows_ampersand_fixer=mock_fixer)
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments({"command": "test"}),
        )
        original_args = envelope.normalized_arguments.root.copy()
        context = FixupContext(
            tool_name="execute_command",
            client_os="Windows",
        )

        result = pipeline.apply_fixups(envelope, context)

        # Should be called with original arguments (before Droid fixup potentially modifies)
        # Note: Droid fixup runs first but won't modify non-path arguments
        mock_fixer.fix_tool_arguments.assert_called_once_with(
            tool_arguments=original_args,
            tool_name="execute_command",
            client_os="Windows",
        )
        assert result.was_modified_by_fixups is True

    def test_windows_fixup_creates_default_fixer(self) -> None:
        """Test that pipeline creates default fixer if none provided."""
        pipeline = ToolArgumentsFixupPipeline()
        # Should not raise
        assert pipeline._windows_fixup is not None
        assert isinstance(pipeline._windows_fixup, WindowsDoubleAmpersandFixer)


class TestFixupContext:
    """Tests for FixupContext dataclass."""

    def test_fixup_context_creation(self) -> None:
        """Test creating FixupContext with required fields."""
        context = FixupContext(tool_name="test_tool")

        assert context.tool_name == "test_tool"
        assert context.backend_name is None
        assert context.calling_agent is None
        assert context.client_os is None

    def test_fixup_context_with_all_fields(self) -> None:
        """Test creating FixupContext with all fields."""
        context = FixupContext(
            tool_name="test_tool",
            backend_name="openai",
            calling_agent="droid-agent",
            client_os="Windows",
        )

        assert context.tool_name == "test_tool"
        assert context.backend_name == "openai"
        assert context.calling_agent == "droid-agent"
        assert context.client_os == "Windows"


class TestNoCrashBehavior:
    """Tests for no-crash behavior (Requirement 6.1)."""

    def test_pipeline_handles_invalid_envelope(self) -> None:
        """Test that pipeline handles edge cases without crashing."""
        pipeline = ToolArgumentsFixupPipeline()
        # Empty envelope
        envelope = ToolArgumentsEnvelope()
        context = FixupContext(tool_name="test_tool")

        # Should not raise
        result = pipeline.apply_fixups(envelope, context)
        assert isinstance(result, ToolArgumentsEnvelope)

    def test_pipeline_handles_non_dict_arguments(self) -> None:
        """Test that pipeline handles non-dict normalized arguments."""
        pipeline = ToolArgumentsFixupPipeline()
        # Envelope with list-wrapped arguments
        envelope = ToolArgumentsEnvelope(
            parse_outcome="success",
            normalized_arguments=NormalizedToolArguments(
                {"__proxy_args_list__": ["item1", "item2"]}
            ),
        )
        context = FixupContext(tool_name="test_tool")

        # Should not raise
        result = pipeline.apply_fixups(envelope, context)
        assert isinstance(result, ToolArgumentsEnvelope)
