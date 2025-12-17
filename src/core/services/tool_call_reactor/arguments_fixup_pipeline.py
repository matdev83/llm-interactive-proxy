"""
Tool arguments fixup pipeline with composable fixup steps.

This module implements a composable pipeline for applying best-effort fixups
to tool arguments, such as path normalization and Windows command separator fixes.
"""

from __future__ import annotations

from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
    FixupContext,
    IToolArgumentsFixupPipeline,
)
from src.core.interfaces.tool_call_reactor_internal import ToolArgumentsEnvelope
from src.core.services.tool_call_reactor.fixups.droid_path_fixup import (
    DroidPathFixup,
)
from src.core.services.windows_double_ampersand_fixer import (
    WindowsDoubleAmpersandFixer,
)


class ToolArgumentsFixupPipeline(IToolArgumentsFixupPipeline):
    """Pipeline for applying composable fixups to tool arguments.

    This pipeline applies a series of best-effort fixups:
    1. Droid/Antigravity path normalization
    2. Windows double-ampersand command separator fixes

    Fixups are applied sequentially, and the pipeline tracks whether any
    modifications were made via the was_modified_by_fixups flag.
    """

    def __init__(
        self,
        windows_ampersand_fixer: WindowsDoubleAmpersandFixer | None = None,
    ) -> None:
        """Initialize the fixup pipeline.

        Args:
            windows_ampersand_fixer: Optional Windows ampersand fixer.
                If None, a new instance is created.
        """
        self._droid_fixup = DroidPathFixup()
        self._windows_fixup = windows_ampersand_fixer or WindowsDoubleAmpersandFixer()

    def apply_fixups(
        self,
        envelope: ToolArgumentsEnvelope,
        context: FixupContext,
    ) -> ToolArgumentsEnvelope:
        """Apply fixups to tool arguments.

        This method applies fixup steps sequentially:
        1. Droid path normalization (if agent matches)
        2. Windows ampersand fixes (if client OS and tool match)

        Args:
            envelope: The tool arguments envelope to apply fixups to.
                This envelope is modified in-place.
            context: Context information for fixup activation decisions.

        Returns:
            The same envelope instance (modified in-place) with
            was_modified_by_fixups=True if any fixup applied changes.
        """
        # Work with the normalized arguments dict
        args_dict = envelope.normalized_arguments.root
        any_modified = False

        # Apply Droid path fixup
        if isinstance(args_dict, dict):
            fixed_args, droid_modified = self._droid_fixup.apply(
                args_dict, context.calling_agent
            )
            if droid_modified:
                envelope.normalized_arguments.root = fixed_args
                any_modified = True
                args_dict = fixed_args

        # Apply Windows ampersand fixup
        fixed_args, ampersand_modified = self._windows_fixup.fix_tool_arguments(
            tool_arguments=args_dict,
            tool_name=context.tool_name,
            client_os=context.client_os,
        )
        if ampersand_modified:
            # Update normalized arguments if fixup modified them
            if isinstance(fixed_args, dict):
                envelope.normalized_arguments.root = fixed_args
            else:
                # If fixup returned a string, wrap it appropriately
                # This should be rare - Windows fixup typically works with dicts
                from src.core.interfaces.tool_call_reactor_internal import (
                    normalize_tool_arguments,
                )

                # Preserve existing parse outcome and raw arguments
                new_envelope = normalize_tool_arguments(
                    fixed_args,
                    parse_outcome=envelope.parse_outcome,
                    was_modified_by_fixups=True,
                )
                new_envelope.raw_arguments = envelope.raw_arguments
                envelope.normalized_arguments = new_envelope.normalized_arguments

            any_modified = True

        # Update modification flag
        if any_modified:
            envelope.was_modified_by_fixups = True

        return envelope
