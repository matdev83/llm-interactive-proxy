from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.chat import ToolCall


class ToolTextRenderer(ABC):
    """Abstract base class for tool text renderers."""

    @abstractmethod
    def render(self, tool_call: ToolCall) -> str | None:
        """Render a tool call to a textual representation."""
        raise NotImplementedError


class NoOpRenderer(ToolTextRenderer):
    """A renderer that produces no output."""

    def render(self, tool_call: ToolCall) -> str | None:
        return None


class XmlRenderer(ToolTextRenderer):
    """Renders tool calls as XML, similar to the legacy Kilo/Cline format."""

    def render(self, tool_call: ToolCall) -> str | None:
        if tool_call.function.name == "shell":
            try:
                args = json.loads(tool_call.function.arguments)
                command_arg = args.get("command", [])
                if isinstance(command_arg, list):
                    command = " ".join(command_arg)
                else:
                    command = str(command_arg)
                return (
                    f"<execute_command><command>{command}</command></execute_command>"
                )
            except (json.JSONDecodeError, AttributeError):
                return None
        if tool_call.function.name == "apply_patch":
            try:
                args = json.loads(tool_call.function.arguments)
                path = args.get("path")
                diff = args.get("diff")
                if path and diff:
                    return f"<apply_diff><path>{path}</path><diff>{diff}</diff></apply_diff>"
            except (json.JSONDecodeError, AttributeError):
                return None
        if tool_call.function.name == "view_image":
            try:
                args = json.loads(tool_call.function.arguments)
                path = args.get("path")
                if path:
                    return f"<view_image><path>{path}</path></view_image>"
            except (json.JSONDecodeError, AttributeError):
                return None
        return None


class RendererRegistry:
    """A registry for tool text renderers."""

    def __init__(self) -> None:
        self._renderers: dict[str, ToolTextRenderer] = {
            "none": NoOpRenderer(),
            "xml": XmlRenderer(),
        }

    def register(self, name: str, renderer: ToolTextRenderer) -> None:
        """Register a new renderer."""
        self._renderers[name] = renderer

    def get(self, name: str) -> ToolTextRenderer:
        """Get a renderer by name."""
        return self._renderers.get(name, NoOpRenderer())


_renderer_registry = RendererRegistry()


def get_renderer(name: str) -> ToolTextRenderer:
    """Get a renderer from the global registry."""
    return _renderer_registry.get(name)


def register_renderer(name: str, renderer: ToolTextRenderer) -> None:
    """Register a renderer in the global registry."""
    _renderer_registry.register(name, renderer)


# Context manager to temporarily override the renderer for a block of code
_override: str | None = None


class OverrideRenderer:
    def __init__(self, renderer_name: str):
        self.renderer_name = renderer_name
        self.original_override = _override

    def __enter__(self) -> None:
        global _override
        _override = self.renderer_name

    def __exit__(self, exc_type: Any, _: Any, traceback: Any) -> None:
        global _override
        _override = self.original_override


def render_tool_call(tool_call: ToolCall) -> str | None:
    """Render a tool call using the currently active renderer."""
    renderer_name = _override or "none"
    renderer = get_renderer(renderer_name)
    return renderer.render(tool_call)
