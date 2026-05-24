"""
Interface for tool arguments fixup pipeline in the tool-call reactor subsystem.

This module defines the interface for components that apply composable fixups
to tool arguments (e.g., path normalization, Windows separator fixes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.interfaces.tool_call_reactor_internal import ToolArgumentsEnvelope


@dataclass
class FixupContext:
    """Context information for applying argument fixups.

    This context provides the information needed by fixup steps to determine
    whether they should activate and how to apply their transformations.
    """

    tool_name: str
    """Name of the tool being invoked."""

    backend_name: str | None = None
    """Name of the backend that generated the tool call."""

    calling_agent: str | None = None
    """User-Agent or agent identifier from the request."""

    client_os: str | None = None
    """Detected client operating system."""


class IToolArgumentsFixupPipeline(ABC):
    """Interface for applying composable fixups to tool arguments.

    This pipeline applies a series of best-effort fixups to tool arguments,
    such as path normalization for Droid/Antigravity agents and Windows
    command separator fixes. Fixups are applied sequentially, and the pipeline
    tracks whether any modifications were made.

    The pipeline modifies the ToolArgumentsEnvelope in-place and sets
    was_modified_by_fixups=True if any fixup applied changes.
    """

    @abstractmethod
    def apply_fixups(
        self,
        envelope: ToolArgumentsEnvelope,
        context: FixupContext,
    ) -> ToolArgumentsEnvelope:
        """Apply fixups to tool arguments.

        This method applies a series of fixup steps to the provided envelope,
        modifying normalized_arguments.root in-place when fixups apply.
        The was_modified_by_fixups flag is set to True if any fixup made changes.

        Args:
            envelope: The tool arguments envelope to apply fixups to.
                This envelope is modified in-place.
            context: Context information for fixup activation decisions.

        Returns:
            The same envelope instance (modified in-place) with
            was_modified_by_fixups=True if any fixup applied changes.

        Note:
            Fixups are best-effort and should not raise exceptions.
            If a fixup cannot apply, it should leave the envelope unchanged.
        """
        ...
