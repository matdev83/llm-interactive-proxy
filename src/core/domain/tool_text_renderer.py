from __future__ import annotations

import importlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from src.core.domain.chat import ToolCall

logger = logging.getLogger(__name__)


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
                workdir = args.get("workdir")
                workdir_xml = (
                    f"<cwd>{workdir}</cwd>" if isinstance(workdir, str) else ""
                )
                return f"<execute_command><command>{command}</command>{workdir_xml}</execute_command>"
            except (json.JSONDecodeError, AttributeError):
                return None
        if tool_call.function.name == "apply_patch":
            try:
                args = json.loads(tool_call.function.arguments)
                path = args.get("path")
                diff = args.get("diff") or args.get("patch")
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


class MarkdownRenderer(ToolTextRenderer):
    """Render tool calls into lightweight Markdown blocks."""

    @staticmethod
    def _load_arguments(tool_call: ToolCall) -> dict[str, Any]:
        try:
            args = json.loads(tool_call.function.arguments or "{}")
            if isinstance(args, dict):
                return args
        except (json.JSONDecodeError, TypeError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to decode tool arguments for Markdown renderer",
                    exc_info=True,
                )
        return {}

    def render(self, tool_call: ToolCall) -> str | None:
        name = tool_call.function.name
        args = self._load_arguments(tool_call)
        if name == "shell":
            command_value = args.get("command", [])
            if isinstance(command_value, list | tuple):
                command_str = " ".join(str(part) for part in command_value)
            else:
                command_str = str(command_value) if command_value else ""
            workdir = args.get("workdir")
            header = f"```bash\n{command_str}\n```".strip()
            if not header:
                return None
            if isinstance(workdir, str) and workdir.strip():
                return f"{header}\n\n_Working directory_: `{workdir}`"
            return header
        if name == "apply_patch":
            diff = args.get("diff") or args.get("patch")
            if not isinstance(diff, str):
                return None
            path = args.get("path")
            path_line = f"Target: `{path}`\n\n" if isinstance(path, str) else ""
            return f"{path_line}```diff\n{diff}\n```"
        if name == "view_image":
            path = args.get("path")
            if isinstance(path, str):
                return f"![Requested image]({path})"
        return None


class SummaryRenderer(ToolTextRenderer):
    """Fallback renderer that provides a concise textual summary."""

    def render(self, tool_call: ToolCall) -> str | None:
        name = tool_call.function.name or "unknown"
        arguments = tool_call.function.arguments
        snippet = arguments.strip() if isinstance(arguments, str) else str(arguments)
        if len(snippet) > 200:
            snippet = f"{snippet[:197]}..."
        return f"[tool:{name}] {snippet}"


class RendererRegistry:
    """A registry for tool text renderers."""

    def __init__(self) -> None:
        self._set_defaults()

    def _set_defaults(self) -> None:
        self._renderers: dict[str, ToolTextRenderer] = {
            "none": NoOpRenderer(),
            "xml": XmlRenderer(),
            "markdown": MarkdownRenderer(),
            "summary": SummaryRenderer(),
        }
        self._aliases: dict[str, str] = {
            "codex_xml": "xml",
        }
        self._default_renderer: str = "none"
        self._fallback_renderer: str = "summary"

    def register(self, name: str, renderer: ToolTextRenderer) -> None:
        """Register a new renderer instance."""
        key = name.strip().lower()
        if not key:
            raise ValueError("Renderer name cannot be empty")
        self._renderers[key] = renderer

    def register_alias(self, alias: str, target: str) -> None:
        """Register an alias for an existing renderer."""
        alias_key = alias.strip().lower()
        target_key = target.strip().lower()
        if not alias_key or not target_key:
            raise ValueError("Alias and target names cannot be empty")
        self._aliases[alias_key] = target_key

    def register_factory(
        self, name: str, factory: Callable[[], ToolTextRenderer]
    ) -> None:
        """Register a renderer created by a factory callable."""
        renderer = factory()
        self.register(name, renderer)

    def register_module(self, name: str, dotted_path: str) -> None:
        """Register a renderer from a dotted import path."""
        module_path, _, attribute = dotted_path.rpartition(".")
        if not module_path or not attribute:
            raise ValueError(
                f"Invalid renderer path '{dotted_path}'. Expected format 'module.ClassName'."
            )
        module = importlib.import_module(module_path)
        candidate = getattr(module, attribute, None)
        if candidate is None:
            raise AttributeError(f"{dotted_path} does not reference an attribute")
        if isinstance(candidate, ToolTextRenderer):
            renderer = candidate
        elif callable(candidate):
            renderer = candidate()  # type: ignore[call-arg]
        else:
            renderer = candidate  # type: ignore[assignment]
        if not isinstance(renderer, ToolTextRenderer):
            raise TypeError(
                f"Renderer '{dotted_path}' is not an instance of ToolTextRenderer"
            )
        self.register(name, renderer)

    def set_default(self, name: str) -> None:
        """Set the default renderer name."""
        candidate = self._aliases.get(name, name)
        if candidate not in self._renderers:
            raise KeyError(f"Renderer '{name}' is not registered")
        self._default_renderer = candidate

    def set_fallback(self, name: str) -> None:
        """Set the fallback renderer name."""
        candidate = self._aliases.get(name, name)
        if candidate not in self._renderers:
            raise KeyError(f"Renderer '{name}' is not registered")
        self._fallback_renderer = candidate

    def configure(
        self,
        *,
        aliases: dict[str, str] | None = None,
        factories: dict[str, Callable[[], ToolTextRenderer]] | None = None,
        modules: dict[str, str] | None = None,
        default: str | None = None,
        fallback: str | None = None,
    ) -> None:
        """Bulk configure the registry."""
        if modules:
            for name, path in modules.items():
                try:
                    self.register_module(name, path)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to register renderer %s from %s: %s",
                        name,
                        path,
                        exc,
                        exc_info=True,
                    )
        if factories:
            for name, factory in factories.items():
                try:
                    self.register_factory(name, factory)
                except Exception as exc:  # pragma: no cover - defensive logging
                    logger.warning(
                        "Failed to register renderer %s from factory: %s",
                        name,
                        exc,
                        exc_info=True,
                    )
        if aliases:
            for alias, target in aliases.items():
                self.register_alias(alias, target)
        if default:
            self.set_default(default)
        if fallback:
            self.set_fallback(fallback)

    def get(self, name: str | None) -> ToolTextRenderer:
        """Get a renderer by name, applying aliases and defaults."""
        key = (name or self._default_renderer).strip().lower()
        key = self._aliases.get(key, key)
        return self._renderers.get(key, self._renderers[self._default_renderer])

    @property
    def default_renderer(self) -> str:
        return self._default_renderer

    @property
    def fallback_renderer(self) -> str:
        return self._fallback_renderer

    def reset(self) -> None:
        """Reset registry to default state."""
        self._set_defaults()


_renderer_registry = RendererRegistry()


def get_renderer(name: str | None) -> ToolTextRenderer:
    """Get a renderer from the global registry."""
    return _renderer_registry.get(name)


def register_renderer(name: str, renderer: ToolTextRenderer) -> None:
    """Register a renderer in the global registry."""
    _renderer_registry.register(name, renderer)


def configure_renderer_registry(**kwargs: Any) -> None:
    """Helper to configure the global renderer registry."""
    _renderer_registry.configure(**kwargs)


def reset_renderer_registry() -> None:
    """Reset the global renderer registry to its defaults."""
    _renderer_registry.reset()


_override: str | None = None


class OverrideRenderer:
    def __init__(self, renderer_name: str):
        self.renderer_name = renderer_name
        self.original_override = _override

    def __enter__(self) -> None:
        global _override
        _override = self.renderer_name

    def __exit__(self, _exc_type: Any, _: Any, _traceback: Any) -> None:
        global _override
        _override = self.original_override


def render_tool_call(tool_call: ToolCall) -> str | None:
    """Render a tool call using the currently active renderer."""
    renderer_name = _override or _renderer_registry.default_renderer
    renderer = get_renderer(renderer_name)
    text = renderer.render(tool_call)
    if text:
        return text
    if (_override or "").strip().lower() in {"", "none"}:
        return None
    fallback_name = _renderer_registry.fallback_renderer
    if fallback_name and fallback_name != renderer_name:
        fallback_renderer = get_renderer(fallback_name)
        try:
            return fallback_renderer.render(tool_call)
        except (AttributeError, TypeError, ValueError) as exc:
            # Renderer-specific errors - log with context and return None
            function_name = tool_call.function.name if tool_call.function else "unknown"
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Fallback renderer %s failed for tool call %s: %s",
                    fallback_name,
                    function_name,
                    exc,
                    exc_info=True,
                )
    return None
