from __future__ import annotations

import json
import logging
import shlex
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

ToolTextRenderer = Callable[
    [str | None, str | Mapping[str, Any] | None, str | None, dict[str, Any] | None],
    str | None,
]

_renderer_registry: dict[str, ToolTextRenderer] = {}
_renderer_context: ContextVar[str] = ContextVar(
    "tool_text_renderer_key", default="codex_xml"
)


def register_renderer(name: str, renderer: ToolTextRenderer) -> None:
    """Register a tool text renderer under the given name."""
    _renderer_registry[name] = renderer


def get_renderer(name: str | None = None) -> ToolTextRenderer | None:
    """Return the renderer for the given name or the currently active context."""
    key = name or _renderer_context.get()
    return _renderer_registry.get(key)


def set_renderer(name: str) -> Any:
    """Set the active renderer for the current task and return the context token."""
    return _renderer_context.set(name)


def reset_renderer(token: Any) -> None:
    """Reset the renderer context using the token returned from set_renderer."""
    try:
        _renderer_context.reset(token)
    except ValueError:
        logger.debug("Renderer context reset skipped due to context mismatch")


@contextmanager
def override_renderer(name: str) -> Any:
    """Context manager to temporarily override the active renderer."""
    token = set_renderer(name)
    try:
        yield
    finally:
        reset_renderer(token)


def render_tool_call_text(
    tool_name: str | None,
    arguments: str | Mapping[str, Any] | None,
    call_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    renderer: str | None = None,
) -> str | None:
    """Render textual representation for a tool call."""
    func = get_renderer(renderer)
    if not func:
        return None
    try:
        return func(tool_name, arguments, call_id, metadata)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning(
            "Tool text renderer '%s' failed: %s",
            renderer or _renderer_context.get(),
            exc,
            exc_info=True,
        )
        return None


def _ensure_arguments_dict(
    arguments: str | Mapping[str, Any] | None
) -> tuple[dict[str, Any], str | None]:
    """Normalize tool arguments into dict and raw string."""
    parsed_arguments: dict[str, Any] = {}
    raw_arguments: str | None = None

    if isinstance(arguments, Mapping):
        parsed_arguments = dict(arguments)
        raw_arguments = json.dumps(arguments)
    elif isinstance(arguments, str):
        raw_arguments = arguments
        try:
            candidate = json.loads(arguments)
            if isinstance(candidate, Mapping):
                parsed_arguments = dict(candidate)
        except Exception:
            parsed_arguments = {}
    elif arguments is not None:
        raw_arguments = str(arguments)
    return parsed_arguments, raw_arguments


def _codex_xml_renderer(
    tool_name: str | None,
    arguments: str | Mapping[str, Any] | None,
    call_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Render tool calls using the historical Codex XML envelope."""
    name = (tool_name or "").strip()
    parsed_arguments, raw_arguments = _ensure_arguments_dict(arguments)

    def _join_command(command_value: Any) -> str:
        if isinstance(command_value, list | tuple):
            try:
                return shlex.join(str(part) for part in command_value)
            except Exception:
                return " ".join(str(part) for part in command_value)
        if isinstance(command_value, str):
            return command_value
        return str(command_value) if command_value is not None else ""

    if name == "shell":
        command_value = parsed_arguments.get("command")
        command_str = _join_command(command_value)
        cwd_value = parsed_arguments.get("workdir") or parsed_arguments.get("cwd") or ""
        parts = ["<execute_command>"]
        if command_str:
            parts.append(f"<command>{command_str}</command>")
        if cwd_value:
            parts.append(f"<cwd>{cwd_value}</cwd>")
        parts.append("</execute_command>")
        return "".join(parts)

    if name == "apply_patch":
        if isinstance(arguments, str):
            diff_text = arguments
        elif isinstance(parsed_arguments.get("patch"), str):
            diff_text = parsed_arguments["patch"]
        else:
            diff_text = raw_arguments or ""
        diff_text = diff_text.strip("\n")
        parts = ["<apply_diff>"]
        path_value = parsed_arguments.get("path")
        if isinstance(path_value, str) and path_value:
            parts.append(f"<path>{path_value}</path>")
        parts.append("<diff>")
        if diff_text:
            parts.append(diff_text)
        parts.append("</diff>")
        parts.append("</apply_diff>")
        return "".join(parts)

    if name == "view_image":
        path = parsed_arguments.get("path") or raw_arguments or ""
        if path:
            return "<view_image>" f"<path>{path}</path>" "</view_image>"
        return "<view_image><path></path></view_image>"

    if name:
        summary_parts = [f"[Tool {name} invoked]"]
        if parsed_arguments:
            try:
                summary_parts.append(json.dumps(parsed_arguments))
            except Exception:
                summary_parts.append(str(parsed_arguments))
        elif raw_arguments:
            summary_parts.append(raw_arguments)
        return " ".join(summary_parts)

    return None


def _none_renderer(
    tool_name: str | None,
    arguments: str | Mapping[str, Any] | None,
    call_id: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Renderer that disables textual tool call output."""
    return None


register_renderer("codex_xml", _codex_xml_renderer)
register_renderer("xml", _codex_xml_renderer)
register_renderer("none", _none_renderer)
