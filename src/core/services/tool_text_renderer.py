"""Tool call text rendering services.

This module remains as a backward-compatible import path for the renderer
registry and helpers. The implementation lives in `src.core.domain.tool_text_renderer`
so domain-layer translation code does not depend on service-layer modules.
"""

from __future__ import annotations

from src.core.domain.tool_text_renderer import (
    MarkdownRenderer,
    NoOpRenderer,
    OverrideRenderer,
    RendererRegistry,
    SummaryRenderer,
    ToolTextRenderer,
    XmlRenderer,
    configure_renderer_registry,
    get_renderer,
    register_renderer,
    render_tool_call,
    reset_renderer_registry,
)

__all__ = [
    "MarkdownRenderer",
    "NoOpRenderer",
    "OverrideRenderer",
    "RendererRegistry",
    "SummaryRenderer",
    "ToolTextRenderer",
    "XmlRenderer",
    "configure_renderer_registry",
    "get_renderer",
    "register_renderer",
    "render_tool_call",
    "reset_renderer_registry",
]
