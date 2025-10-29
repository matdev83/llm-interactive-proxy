r"""
OpenAI Codex connector that uses ChatGPT/Codex auth.json tokens instead of API keys.

This backend reads a local `auth.json` file (created by Codex CLI via ChatGPT login)
and uses `tokens.access_token` as the bearer for OpenAI API requests. If the file
also contains `OPENAI_API_KEY`, that is used as a fallback.

Default credential file locations (first that exists is used):
- Windows: %USERPROFILE%\.codex\auth.json
- Cross-platform: ~/.codex/auth.json

Configuration:
- `openai_codex_path`: optional directory that contains `auth.json` (overrides defaults)
- `openai_api_base_url`: optional base URL override (default: https://api.openai.com/v1)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import HTTPException
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

from src.connectors._openai_codex_capabilities import (
    CodexCapabilityResolver,
    CodexClientCapabilities,
)
from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
from src.connectors._openai_codex_request_translator import CodexRequestTranslator
from src.connectors._openai_codex_session_detector import SessionDetector
from src.connectors.openai import OpenAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry
from src.core.services.tool_text_renderer import (
    OverrideRenderer,
    configure_renderer_registry,
)
from src.core.services.translation_service import TranslationService
from src.core.services.universal_tool_executor import UniversalToolExecutor

logger = logging.getLogger(__name__)


def _load_json_env(var_name: str) -> Any:
    """Parse a JSON environment variable, returning None on failure."""
    raw_value = os.getenv(var_name)
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid JSON in %s", var_name)
        return None


def _to_mapping(candidate: Any) -> dict[str, Any] | None:
    """Convert arbitrary objects into plain dictionaries when possible."""
    if candidate is None:
        return None
    if isinstance(candidate, Mapping):
        return dict(candidate)
    if hasattr(candidate, "model_dump") and callable(candidate.model_dump):
        try:
            dumped = candidate.model_dump()
            if isinstance(dumped, Mapping):
                return dict(dumped)
        except Exception:
            return None
    if hasattr(candidate, "__dict__"):
        return dict(candidate.__dict__)
    return None


def _coerce_positive_int(value: Any) -> int | None:
    """Return a positive int coerced from arbitrary input."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        if not value.strip().isdigit():
            return None
        numeric = int(value.strip())
        return numeric if numeric >= 0 else None
    return None


def _coerce_float_sequence(value: Any) -> tuple[float, ...] | None:
    """Convert a value into a tuple of non-negative floats."""
    if value is None:
        return None
    if isinstance(value, list | tuple | set):
        result: list[float] = []
        for item in value:
            try:
                numeric = float(item)
            except (TypeError, ValueError):
                continue
            if numeric < 0:
                continue
            result.append(numeric)
        return tuple(result)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parts = [part.strip() for part in value.split(",")]
            return _coerce_float_sequence(parts)
        else:
            return _coerce_float_sequence(parsed)
    return None


def _to_string_list(value: Any) -> list[str]:
    """Normalize various containers into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    result.append(text)
        return result
    return []


def _validate_tool_schema(
    schema: dict[str, Any], context: str
) -> tuple[bool, list[str]]:
    """Validate a tool schema dictionary.

    Returns:
        (is_valid, list_of_errors)
    """
    errors: list[str] = []

    # Required: name field
    name = schema.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"{context}: Missing or invalid 'name' field")

    # Optional but recommended: description
    if "description" in schema:
        desc = schema.get("description")
        if not isinstance(desc, str):
            errors.append(f"{context}: 'description' must be a string")

    # Optional but common: parameters
    if "parameters" in schema:
        params = schema.get("parameters")
        if not isinstance(params, dict):
            errors.append(f"{context}: 'parameters' must be an object")
        elif "type" in params and params.get("type") != "object":
            errors.append(f"{context}: 'parameters.type' should be 'object'")

    return len(errors) == 0, errors


def _normalize_tool_schema_list(value: Any, *, context: str) -> list[dict[str, Any]]:
    """Normalize a value into a list of tool schema dictionaries with validation."""
    if value is None:
        return []
    items: Sequence[Any]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        items = value
    else:
        items = [value]
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(items):
        mapping = _to_mapping(entry)
        if not mapping:
            logger.warning(
                "Skipping invalid tool schema entry %s[%s]: not a valid mapping",
                context,
                idx,
            )
            continue

        # Validate the schema
        is_valid, errors = _validate_tool_schema(mapping, f"{context}[{idx}]")
        if not is_valid:
            logger.warning(
                "Skipping invalid tool schema entry %s[%s]: %s",
                context,
                idx,
                "; ".join(errors),
            )
            continue

        normalized.append(dict(mapping))
    return normalized


class OpenAICredentialsFileHandler(FileSystemEventHandler):
    """File watcher handler for OpenAI Codex credentials."""

    def __init__(self, connector: OpenAICodexConnector) -> None:
        super().__init__()
        self.connector = connector

    def on_modified(self, event) -> None:  # type: ignore[no-untyped-def]
        """Handle file modification events."""
        if not event.is_directory and isinstance(event.src_path, str):
            # Compare paths using Path objects to handle Windows/Unix differences
            try:
                event_path = Path(event.src_path).resolve()
                auth_path = (
                    self.connector._auth_path.resolve()
                    if self.connector._auth_path
                    else None
                )

                if auth_path and event_path == auth_path:
                    logger.debug(
                        "OpenAI Codex credentials file changed, scheduling reload"
                    )
                    self.connector._schedule_credentials_reload()
            except Exception as e:
                logger.error(f"Error processing file modification event: {e}")


class OpenAICodexConnector(OpenAIConnector):
    backend_type: str = "openai-codex"
    CODEX_PROMPT_RESOURCE_PACKAGE = "src.resources.codex"
    CODEX_PROMPT_RESOURCE_NAME = "gpt_5_codex_prompt.md"
    CODEX_ORIGINATOR = "codex_cli_rs"
    CODEX_VERSION_HEADER = "0.0.0"

    @classmethod
    @lru_cache(maxsize=1)
    def _codex_system_prompt(cls) -> str:
        """Load the Codex system prompt from bundled resources or vendor sources."""
        try:
            from importlib import resources as importlib_resources

            return importlib_resources.read_text(
                cls.CODEX_PROMPT_RESOURCE_PACKAGE,
                cls.CODEX_PROMPT_RESOURCE_NAME,
                encoding="utf-8",
            )
        except (FileNotFoundError, ModuleNotFoundError):
            pass
        except Exception as exc:  # pragma: no cover - diagnostic path
            logger.warning(
                "Failed to load Codex system prompt from package resources: %s", exc
            )

        fallback_paths = [
            Path(__file__).resolve().parents[2]
            / "dev"
            / "thrdparty"
            / "codex"
            / "codex-rs"
            / "core"
            / cls.CODEX_PROMPT_RESOURCE_NAME,
            Path(__file__).resolve().parents[1]
            / "resources"
            / "codex"
            / cls.CODEX_PROMPT_RESOURCE_NAME,
        ]
        for candidate in fallback_paths:
            try:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8")
            except Exception as exc:  # pragma: no cover - diagnostic path
                logger.warning(
                    "Failed loading Codex prompt from %s: %s", candidate, exc
                )

        raise RuntimeError(
            "Codex system prompt not found. Ensure gpt_5_codex_prompt.md is bundled."
        )

    @staticmethod
    def _sanitize_header_value(value: str) -> str:
        """Replace characters outside the visible ASCII range with underscores."""
        return "".join(ch if 32 <= ord(ch) <= 126 else "_" for ch in value)

    @staticmethod
    def _detect_terminal_user_agent() -> str:
        """Best effort reproduction of codex-rs terminal::user_agent detection."""
        term_program = os.getenv("TERM_PROGRAM", "").strip()
        if term_program:
            version = os.getenv("TERM_PROGRAM_VERSION", "").strip()
            base = f"{term_program}/{version}" if version else term_program
        elif wez := os.getenv("WEZTERM_VERSION", "").strip():
            base = f"WezTerm/{wez}" if wez else "WezTerm"
        elif os.getenv("KITTY_WINDOW_ID") or "kitty" in os.getenv("TERM", ""):
            base = "kitty"
        elif os.getenv("ALACRITTY_SOCKET") or os.getenv("TERM", "") == "alacritty":
            base = "Alacritty"
        elif konsole := os.getenv("KONSOLE_VERSION", "").strip():
            base = f"Konsole/{konsole}" if konsole else "Konsole"
        elif os.getenv("GNOME_TERMINAL_SCREEN"):
            base = "gnome-terminal"
        elif vte := os.getenv("VTE_VERSION", "").strip():
            base = f"VTE/{vte}" if vte else "VTE"
        elif os.getenv("WT_SESSION"):
            base = "WindowsTerminal"
        else:
            base = os.getenv("TERM", "unknown")
        return OpenAICodexConnector._sanitize_header_value(base)

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
    ) -> None:
        # Use explicit keywords to avoid argument order issues
        super().__init__(
            client=client,
            config=config,
            translation_service=translation_service,
            response_processor=response_processor,
        )
        self.name = "openai-codex"
        self._oauth_dir_override: Path | None = None
        self._auth_path: Path | None = None
        self._last_modified: float = 0.0
        self.is_functional: bool = False
        self._connector_settings = self._load_connector_settings(config)
        self._default_capabilities: CodexClientCapabilities = self._connector_settings[
            "default_capabilities"
        ]
        self._renderer_default: str = self._connector_settings["renderer"]["default"]
        self._renderer_fallback: str = self._connector_settings["renderer"]["fallback"]
        self._prompt_settings: dict[str, Any] = self._connector_settings["prompt"]
        self._default_tool_schema_override: list[dict[str, Any]] | None = (
            self._connector_settings["tool_schema"]["base_tools"]
        )
        self._custom_tool_schema_default: list[dict[str, Any]] = (
            self._connector_settings["tool_schema"]["custom_tools"]
        )
        streaming_cfg = self._connector_settings.get("streaming", {})
        self._stream_retry_limit: int = int(streaming_cfg.get("max_retries", 2))
        backoff_seq = streaming_cfg.get("retry_backoff_seconds") or ()
        self._stream_retry_backoff: tuple[float, ...] = (
            tuple(backoff_seq) if backoff_seq else ()
        )

        # Stale token handling pattern attributes
        # Use BaseObserver for type checking to ensure stop/join are recognized by mypy
        self._file_observer: BaseObserver | None = None
        self._credential_validation_errors: list[str] = []
        self._initialization_failed: bool = False
        self._last_validation_time: float = 0.0
        self._pending_reload_task: asyncio.Future[None] | None = None
        self._auth_credentials: dict[str, Any] | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_event = threading.Event()  # Thread-safe coordination
        self._capability_resolver = CodexCapabilityResolver(
            default_capabilities=self._default_capabilities,
            agent_overrides=self._connector_settings["agent_overrides"],
        )
        self._request_translator = CodexRequestTranslator(self)
        self._token_refresh_lock = asyncio.Lock()
        self._universal_executor: UniversalToolExecutor | None = None

        # Initialize compatibility layer components
        compat_cfg = self._connector_settings["compatibility_layer"]
        self._compatibility_layer_enabled: bool = compat_cfg["enabled"]
        self._session_detector: SessionDetector | None = None
        self._kilo_tool_translator: KiloToolTranslator | None = None
        if self._compatibility_layer_enabled:
            detection_cfg = compat_cfg["detection"]
            self._session_detector = SessionDetector(
                cache_ttl_seconds=detection_cfg["cache_ttl_seconds"],
                heuristic_threshold=detection_cfg["heuristic_threshold"],
            )
            # Initialize tool translator for KiloCode XML tool invocations
            # TODO: Pass session_service once it's available in the connector
            # For now, passing None - session state updates will be skipped
            session_service = getattr(self, "_session_service", None)
            self._kilo_tool_translator = KiloToolTranslator(self, session_service)
            logger.info(
                "Codex-KiloCode compatibility layer enabled (cache_ttl=%ds, heuristic_threshold=%d)",
                detection_cfg["cache_ttl_seconds"],
                detection_cfg["heuristic_threshold"],
            )

        # Health checks are unnecessary for OAuth bearer flow in tests; disable by default
        import contextlib

        with contextlib.suppress(Exception):
            self.disable_health_check()

    def _load_connector_settings(self, app_config: AppConfig) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "default_capabilities": CodexClientCapabilities(),
            "agent_overrides": {},
            "renderer": {
                "default": "none",
                "fallback": "summary",
                "aliases": {},
                "modules": {},
            },
            "prompt": {
                "template": None,
                "prepend": [],
                "append": [],
                "deduplicate": True,
                "fallback_to_default": True,
            },
            "tool_schema": {
                "base_tools": None,
                "custom_tools": [],
            },
            "streaming": {
                "max_retries": 2,
                "retry_backoff_seconds": (0.5, 1.5, 3.0),
            },
            "compatibility_layer": {
                "enabled": False,
                "detection": {
                    "cache_ttl_seconds": 3600,
                    "heuristic_threshold": 2,
                },
                "translation": {
                    "max_tool_execution_timeout": 30,
                    "result_format": "kilo_standard",
                },
                "telemetry": {
                    "log_translations": True,
                    "log_detection": True,
                    "emit_metrics": True,
                },
            },
        }

        backend_config = getattr(app_config.backends, "openai_codex", None)
        backend_extra = {}
        if backend_config and hasattr(backend_config, "extra"):
            try:
                extra_candidate = backend_config.extra
                if isinstance(extra_candidate, Mapping):
                    backend_extra = dict(extra_candidate)
            except Exception:  # pragma: no cover - defensive
                backend_extra = {}

        codex_cfg = _to_mapping(backend_extra.get("codex")) or {}

        # Default capabilities
        for override_source in (
            codex_cfg.get("default_capabilities"),
            _load_json_env("OPENAI_CODEX_DEFAULT_CAPABILITIES"),
        ):
            mapping = _to_mapping(override_source)
            if mapping:
                settings["default_capabilities"] = settings[
                    "default_capabilities"
                ].merge(mapping)

        # Agent overrides
        combined_agent_overrides: dict[str, dict[str, Any]] = {}
        for source in (
            codex_cfg.get("agent_capabilities"),
            _load_json_env("OPENAI_CODEX_AGENT_CAPABILITIES"),
        ):
            mapping = _to_mapping(source)
            if not mapping:
                continue
            for raw_agent, caps in mapping.items():
                if not isinstance(raw_agent, str):
                    continue
                agent_key = raw_agent.strip().lower()
                if not agent_key:
                    continue
                cap_mapping = _to_mapping(caps)
                if not cap_mapping:
                    continue
                combined_agent_overrides.setdefault(agent_key, {}).update(cap_mapping)
        settings["agent_overrides"] = combined_agent_overrides

        # Renderer configuration
        renderer_cfg = _to_mapping(codex_cfg.get("renderer")) or {}
        renderer_aliases = _to_mapping(renderer_cfg.get("aliases")) or {}
        renderer_modules = _to_mapping(renderer_cfg.get("modules")) or {}
        env_renderer_aliases = (
            _to_mapping(_load_json_env("OPENAI_CODEX_RENDERER_ALIASES") or {}) or {}
        )
        env_renderer_modules = (
            _to_mapping(_load_json_env("OPENAI_CODEX_RENDERER_MODULES") or {}) or {}
        )

        renderer_default = renderer_cfg.get("default") or os.getenv(
            "OPENAI_CODEX_RENDERER_DEFAULT"
        )
        renderer_fallback = renderer_cfg.get("fallback") or os.getenv(
            "OPENAI_CODEX_RENDERER_FALLBACK"
        )
        renderer_default = (renderer_default or "none").strip() or "none"
        renderer_fallback = (renderer_fallback or "summary").strip() or "summary"

        # Prompt configuration
        prompt_cfg = _to_mapping(codex_cfg.get("prompt")) or {}
        prompt_template = prompt_cfg.get("template") or os.getenv(
            "OPENAI_CODEX_PROMPT_TEMPLATE"
        )
        prepend_sections = _to_string_list(prompt_cfg.get("prepend")) + _to_string_list(
            _load_json_env("OPENAI_CODEX_PROMPT_PREPEND")
        )
        append_sections = _to_string_list(prompt_cfg.get("append")) + _to_string_list(
            _load_json_env("OPENAI_CODEX_PROMPT_APPEND")
        )
        prompt_deduplicate_env = os.getenv("OPENAI_CODEX_PROMPT_DEDUPLICATE")
        if prompt_deduplicate_env is not None:
            prompt_deduplicate = prompt_deduplicate_env.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            prompt_deduplicate = bool(prompt_cfg.get("deduplicate", True))
        fallback_to_default_env = os.getenv("OPENAI_CODEX_PROMPT_FALLBACK_DEFAULT")
        if fallback_to_default_env is not None:
            fallback_to_default = fallback_to_default_env.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        else:
            fallback_to_default = bool(prompt_cfg.get("fallback_to_default", True))

        settings["prompt"].update(
            {
                "template": (
                    prompt_template.strip()
                    if isinstance(prompt_template, str)
                    else None
                ),
                "prepend": prepend_sections,
                "append": append_sections,
                "deduplicate": prompt_deduplicate,
                "fallback_to_default": fallback_to_default,
            }
        )

        # Tool schema configuration
        tool_schema_cfg = _to_mapping(codex_cfg.get("tool_schema")) or {}
        base_tools = _normalize_tool_schema_list(
            tool_schema_cfg.get("base_tools")
            or _load_json_env("OPENAI_CODEX_TOOL_SCHEMA_BASE"),
            context="codex.tool_schema.base_tools",
        )
        custom_tools = _normalize_tool_schema_list(
            tool_schema_cfg.get("custom_tools")
            or _load_json_env("OPENAI_CODEX_TOOL_SCHEMA_CUSTOM"),
            context="codex.tool_schema.custom_tools",
        )
        settings["tool_schema"].update(
            {
                "base_tools": base_tools or None,
                "custom_tools": custom_tools,
            }
        )

        # Configure renderer registry last so aliases/modules are available before defaults
        combined_aliases_raw: dict[Any, Any] = {}
        combined_aliases_raw.update(renderer_aliases)
        combined_aliases_raw.update(env_renderer_aliases)
        combined_modules_raw: dict[Any, Any] = {}
        combined_modules_raw.update(renderer_modules)
        combined_modules_raw.update(env_renderer_modules)

        sanitized_aliases: dict[str, str] = {}
        for alias, target in combined_aliases_raw.items():
            if not isinstance(alias, str) or not isinstance(target, str):
                continue
            alias_key = alias.strip()
            target_key = target.strip()
            if alias_key and target_key:
                sanitized_aliases[alias_key] = target_key

        sanitized_modules: dict[str, str] = {}
        for name, dotted_path in combined_modules_raw.items():
            if not isinstance(name, str) or not isinstance(dotted_path, str):
                continue
            renderer_name = name.strip()
            path_value = dotted_path.strip()
            if renderer_name and path_value:
                sanitized_modules[renderer_name] = path_value
        try:
            configure_renderer_registry(
                aliases=sanitized_aliases or None,
                modules=sanitized_modules or None,
                default=renderer_default,
                fallback=renderer_fallback,
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to configure tool text renderer registry: %s", exc)

        settings["renderer"].update(
            {
                "default": renderer_default,
                "fallback": renderer_fallback,
                "aliases": sanitized_aliases,
                "modules": sanitized_modules,
            }
        )

        if settings["default_capabilities"].tool_text_format in {
            None,
            "none",
        } and renderer_default not in {None, "", "none"}:
            settings["default_capabilities"] = settings["default_capabilities"].merge(
                {"tool_text_format": renderer_default}
            )

        logger.debug(
            "Codex connector settings loaded: default_capabilities=%s, renderer_default=%s, renderer_fallback=%s",
            settings["default_capabilities"].to_dict(),
            renderer_default,
            renderer_fallback,
        )
        # Streaming settings (max retries/backoff)
        streaming_cfg = _to_mapping(codex_cfg.get("streaming")) or {}
        max_retries = _coerce_positive_int(streaming_cfg.get("max_retries"))
        env_max_retries = os.getenv("OPENAI_CODEX_STREAMING_MAX_RETRIES")
        if env_max_retries is not None:
            max_retries_env = _coerce_positive_int(env_max_retries)
            if max_retries_env is not None:
                max_retries = max_retries_env
        if max_retries is None:
            max_retries = settings["streaming"]["max_retries"]

        backoff_seq = (
            _coerce_float_sequence(streaming_cfg.get("retry_backoff_seconds"))
            or settings["streaming"]["retry_backoff_seconds"]
        )
        env_backoff = os.getenv("OPENAI_CODEX_STREAMING_RETRY_BACKOFF")
        if env_backoff:
            maybe_env_backoff = _coerce_float_sequence(env_backoff)
            if maybe_env_backoff:
                backoff_seq = maybe_env_backoff

        if not backoff_seq:
            backoff_seq = (0.5, 1.5, 3.0)

        settings["streaming"] = {
            "max_retries": max_retries,
            "retry_backoff_seconds": tuple(backoff_seq),
        }

        # Compatibility layer settings
        compat_cfg = _to_mapping(codex_cfg.get("compatibility_layer")) or {}

        # Global enable/disable flag
        compat_enabled = compat_cfg.get("enabled")
        env_compat_enabled = os.getenv("OPENAI_CODEX_COMPATIBILITY_LAYER_ENABLED")
        if env_compat_enabled is not None:
            compat_enabled = env_compat_enabled.strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        elif compat_enabled is None:
            compat_enabled = settings["compatibility_layer"]["enabled"]

        # Detection settings
        detection_cfg = _to_mapping(compat_cfg.get("detection")) or {}
        cache_ttl = _coerce_positive_int(detection_cfg.get("cache_ttl_seconds"))
        if cache_ttl is None:
            cache_ttl = settings["compatibility_layer"]["detection"][
                "cache_ttl_seconds"
            ]

        heuristic_threshold = _coerce_positive_int(
            detection_cfg.get("heuristic_threshold")
        )
        if heuristic_threshold is None:
            heuristic_threshold = settings["compatibility_layer"]["detection"][
                "heuristic_threshold"
            ]

        # Translation settings
        translation_cfg = _to_mapping(compat_cfg.get("translation")) or {}
        max_timeout = _coerce_positive_int(
            translation_cfg.get("max_tool_execution_timeout")
        )
        if max_timeout is None:
            max_timeout = settings["compatibility_layer"]["translation"][
                "max_tool_execution_timeout"
            ]

        result_format = (
            translation_cfg.get("result_format")
            or settings["compatibility_layer"]["translation"]["result_format"]
        )

        # Telemetry settings
        telemetry_cfg = _to_mapping(compat_cfg.get("telemetry")) or {}
        log_translations = telemetry_cfg.get("log_translations")
        if log_translations is None:
            log_translations = settings["compatibility_layer"]["telemetry"][
                "log_translations"
            ]

        log_detection = telemetry_cfg.get("log_detection")
        if log_detection is None:
            log_detection = settings["compatibility_layer"]["telemetry"][
                "log_detection"
            ]

        emit_metrics = telemetry_cfg.get("emit_metrics")
        if emit_metrics is None:
            emit_metrics = settings["compatibility_layer"]["telemetry"]["emit_metrics"]

        settings["compatibility_layer"] = {
            "enabled": bool(compat_enabled),
            "detection": {
                "cache_ttl_seconds": cache_ttl,
                "heuristic_threshold": heuristic_threshold,
            },
            "translation": {
                "max_tool_execution_timeout": max_timeout,
                "result_format": str(result_format),
            },
            "telemetry": {
                "log_translations": bool(log_translations),
                "log_detection": bool(log_detection),
                "emit_metrics": bool(emit_metrics),
            },
        }

        return settings

    @staticmethod
    def _is_codex_model(model_name: str) -> bool:
        """Return True when the model routes through the Codex Responses API."""
        lowered = model_name.lower()
        return lowered.startswith(("gpt-5-codex", "codex-"))

    def _codex_user_agent(self) -> str:
        """Build a Codex CLI compatible User-Agent string."""
        system_name = platform.system() or "UnknownOS"
        system_version = (
            platform.version() or platform.release() or os.environ.get("OS", "0")
        )
        arch = platform.machine() or "unknown"
        terminal = self._detect_terminal_user_agent()
        base = (
            f"{self.CODEX_ORIGINATOR}/{self.CODEX_VERSION_HEADER} "
            f"({system_name} {system_version}; {arch}; {terminal}) {terminal}"
        )
        sanitized = self._sanitize_header_value(base)
        if sanitized.strip():
            return sanitized
        return f"{self.CODEX_ORIGINATOR}/{self.CODEX_VERSION_HEADER}"

    def _codex_account_id(self) -> str | None:
        """Return the ChatGPT account_id from cached credentials when available."""
        tokens = None
        if isinstance(self._auth_credentials, dict):
            tokens = self._auth_credentials.get("tokens")
        if isinstance(tokens, dict):
            account_id = tokens.get("account_id")
            if isinstance(account_id, str) and account_id.strip():
                return account_id
        return None

    @staticmethod
    def _message_to_text(message: Any) -> str:
        """Best-effort conversion of a ChatMessage-like object to plain text."""
        # Prefer explicit attributes
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")

        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
                if (
                    not isinstance(part, dict)
                    and hasattr(part, "model_dump")
                    and callable(part.model_dump)
                ):
                    dumped = part.model_dump()
                    if isinstance(dumped, dict):
                        text = dumped.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                            continue
                parts.append(str(part))
            return "\n".join(parts)

        if content is not None:
            return str(content)

        # Fallback to message string representation
        return str(message)

    def _build_environment_context_block(
        self, request_data: Any, effective_model: str
    ) -> str:
        """Compose the <environment_context> block with best-effort metadata."""
        extra_body = getattr(request_data, "extra_body", {}) or {}
        override = extra_body.get("codex_environment_context")
        if isinstance(override, str) and override.strip():
            return override

        cwd = extra_body.get("project_dir") or extra_body.get("cwd")
        if not cwd:
            cwd = os.getcwd()

        sandbox_mode = extra_body.get("sandbox_mode") or "read-only"
        approval_policy = extra_body.get("approval_policy") or "never"
        network_access = extra_body.get("network_access") or "restricted"
        shell_value = extra_body.get("shell") or os.environ.get("SHELL") or "bash"
        if isinstance(shell_value, str) and "/" in shell_value:
            shell_value = shell_value.rsplit("/", 1)[-1] or shell_value
        shell = shell_value or "bash"

        lines = [
            "<environment_context>",
            f"  <cwd>{cwd}</cwd>",
            f"  <approval_policy>{approval_policy}</approval_policy>",
            f"  <sandbox_mode>{sandbox_mode}</sandbox_mode>",
            f"  <network_access>{network_access}</network_access>",
            f"  <shell>{shell}</shell>",
            "</environment_context>",
        ]
        return "\n".join(lines)

    def _default_codex_tools(self) -> list[dict[str, Any]]:
        """Return the tool definitions expected by the Codex Responses API.

        This method dynamically discovers tools from the actual Codex backend
        and includes tools from the universal executor.
        """
        if self._default_tool_schema_override is not None:
            return deepcopy(self._default_tool_schema_override)

        # Get base tools (these would come from actual Codex API discovery in production)
        base_tools = self._get_minimal_base_tools()

        # Add tools from universal executor (MCP tools, etc.)
        executor = self._get_universal_executor()
        universal_tool_schemas = executor.get_tool_schemas()

        # Combine base tools with universal tools
        all_tools = base_tools + universal_tool_schemas

        logger.debug(
            f"Providing {len(all_tools)} tools to Codex: {[t['name'] for t in all_tools]}"
        )
        return all_tools

    def _get_minimal_base_tools(self) -> list[dict[str, Any]]:
        """Return minimal base tools that are universally available.

        This is a fallback when dynamic tool discovery is not available.
        In a full implementation, this should be replaced with actual tool discovery.
        """
        return [
            {
                "type": "function",
                "name": "shell",
                "description": "Runs a shell command and returns its output.",
                "strict": False,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The command to execute",
                        },
                        "workdir": {
                            "type": "string",
                            "description": "The working directory to execute the command in",
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "custom",
                "name": "apply_patch",
                "description": "Use the apply_patch tool to edit files using unified diff syntax.",
                "format": {
                    "type": "grammar",
                    "syntax": "lark",
                    "definition": (
                        "start: begin_patch hunk+ end_patch\n"
                        'begin_patch: "*** Begin Patch" LF\n'
                        'end_patch: "*** End Patch" LF?\n\n'
                        "hunk: add_hunk | delete_hunk | update_hunk\n"
                        'add_hunk: "*** Add File: " filename LF add_line+\n'
                        'delete_hunk: "*** Delete File: " filename LF\n'
                        'update_hunk: "*** Update File: " filename LF change_move? change?\n\n'
                        "filename: /(.+)/\n"
                        'add_line: "+" /(.*)/ LF -> line\n\n'
                        'change_move: "*** Move to: " filename LF\n'
                        "change: (change_context | change_line)+ eof_line?\n"
                        'change_context: ("@@" | "@@ " /(.+)/) LF\n'
                        'change_line: ("+" | "-" | " ") /(.*)/ LF\n'
                        'eof_line: "*** End of File" LF\n\n'
                        "%import common.LF\n"
                    ),
                },
            },
            {
                "type": "function",
                "name": "view_image",
                "description": "Attach a local image (by filesystem path) to the conversation context for this turn.",
                "strict": False,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Local filesystem path to an image file",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        ]

    async def _discover_available_tools(self) -> list[dict[str, Any]]:
        """Dynamically discover available tools from the Codex backend.

        This method should query the actual Codex API to get the current tool schema
        rather than hardcoding tool definitions.
        """
        # TODO: Implement actual tool discovery from Codex API
        # This would involve making a request to the Codex API to get available tools
        # For now, return the minimal base tools
        logger.debug("Tool discovery not yet implemented, using minimal base tools")
        return self._get_minimal_base_tools()

    async def _discover_mcp_tools(self) -> list[dict[str, Any]]:
        """Dynamically discover available MCP tools.

        This method should connect to MCP servers and discover their available tools
        rather than hardcoding MCP tool definitions.
        """
        # TODO: Implement actual MCP tool discovery
        # This would involve connecting to MCP servers and querying their tool schemas
        logger.debug("MCP tool discovery not yet implemented")
        return []

    def _get_universal_executor(self) -> UniversalToolExecutor:
        """Get or create the universal tool executor."""
        if self._universal_executor is None:
            # Initialize with current working directory
            working_dir = os.getcwd()
            self._universal_executor = UniversalToolExecutor(
                working_directory=working_dir
            )
        return self._universal_executor

    async def _execute_universal_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute any tool universally and return formatted result."""
        executor = self._get_universal_executor()
        result = await executor.execute_tool(tool_name, arguments)

        # Format result for Codex compatibility
        output = result.get("output", "")
        exit_code = result.get("exit_code", 0)

        # Add additional metadata if available
        metadata_parts = []
        if "file_path" in result:
            metadata_parts.append(f"File: {result['file_path']}")
        if "directory" in result:
            metadata_parts.append(f"Directory: {result['directory']}")
        if "matches_count" in result:
            metadata_parts.append(f"Matches: {result['matches_count']}")
        if "count" in result:
            metadata_parts.append(f"Items: {result['count']}")
        if "tool_name" in result:
            metadata_parts.append(f"Tool: {result['tool_name']}")

        formatted_output = output
        if metadata_parts:
            metadata_line = " | ".join(metadata_parts)
            formatted_output = f"{output}\n\n[{metadata_line}]"

        return {
            "output": formatted_output,
            "exit_code": exit_code,
            "workdir": os.getcwd(),
            **{k: v for k, v in result.items() if k not in ["output", "exit_code"]},
        }

    async def connect_mcp_server(
        self, server_name: str, server_config: dict[str, Any]
    ) -> bool:
        """Connect to an MCP server to make its tools available.

        Args:
            server_name: Unique name for the server
            server_config: Server configuration

        Returns:
            True if connection successful, False otherwise
        """
        executor = self._get_universal_executor()
        return await executor.connect_mcp_server(server_name, server_config)

    def get_available_tools(self) -> list[str]:
        """Get list of all available tools from the universal executor.

        Returns:
            List of available tool names
        """
        executor = self._get_universal_executor()
        return executor.get_available_tools()

    def _resolve_tool_schema(
        self, request_data: Any, capabilities: CodexClientCapabilities
    ) -> list[dict[str, Any]]:
        """Resolve the tool schema based on capability settings and request data."""
        schema_mode = capabilities.tool_schema_mode
        default_tools = self._default_codex_tools()

        custom_tools_req = getattr(request_data, "tools", []) or []
        custom_tools: list[dict[str, Any]] = []
        for tool in custom_tools_req:
            if hasattr(tool, "model_dump"):
                tool_dict = tool.model_dump(exclude_none=True)
            elif isinstance(tool, dict):
                tool_dict = dict(tool)
            else:
                continue
            name_value = tool_dict.get("name")
            if isinstance(name_value, str) and name_value.strip():
                custom_tools.append(tool_dict)
            else:
                logger.debug(
                    "Ignoring tool without valid name in request payload: %s", tool
                )

        if self._custom_tool_schema_default:
            existing_names = {
                t.get("name") for t in custom_tools if isinstance(t.get("name"), str)
            }
            for tool in self._custom_tool_schema_default:
                name_value = tool.get("name")
                if isinstance(name_value, str) and name_value not in existing_names:
                    custom_tools.append(deepcopy(tool))

        if schema_mode == "custom_only":
            return [deepcopy(tool) for tool in custom_tools]

        if schema_mode == "merge_custom":
            if not custom_tools:
                return default_tools
            merged_tools: dict[str, dict[str, Any]] = {}
            # Track parameter signatures to detect collisions
            tool_signatures: dict[str, str] = {}

            for tool in default_tools:
                name_value = tool.get("name")
                if isinstance(name_value, str):
                    merged_tools[name_value] = deepcopy(tool)
                    # Create signature from parameters for collision detection
                    params = tool.get("parameters", {})
                    tool_signatures[name_value] = json.dumps(params, sort_keys=True)

            for tool in custom_tools:
                name_value = tool.get("name")
                if isinstance(name_value, str):
                    # Check for parameter collision
                    if name_value in merged_tools:
                        params = tool.get("parameters", {})
                        new_sig = json.dumps(params, sort_keys=True)
                        if new_sig != tool_signatures.get(name_value):
                            logger.warning(
                                "Tool schema collision: tool '%s' defined with different parameters. "
                                "Keeping default definition. Custom parameters: %s",
                                name_value,
                                json.dumps(params)[:200],
                            )
                            continue  # Keep default, skip custom
                    merged_tools[name_value] = deepcopy(tool)
                    params = tool.get("parameters", {})
                    tool_signatures[name_value] = json.dumps(params, sort_keys=True)
            return list(merged_tools.values())

        return default_tools

    def _is_native_responses_payload(self, request_data: Any) -> bool:
        """Detect if a request payload is in the native Codex/Responses format with strict validation."""
        # Use a dict-like view of the request_data
        if hasattr(request_data, "model_dump"):
            data = request_data.model_dump()
        elif isinstance(request_data, dict):
            data = request_data
        else:
            return False

        # Early return for obvious OpenAI Chat format (has 'messages' list)
        if (
            "messages" in data
            and isinstance(data.get("messages"), list)
            and not ("prompt_cache_key" in data or "instructions" in data)
        ):
            return False

        # Structural check: does it have an 'input' array with proper structure?
        if "input" in data:
            input_val = data.get("input")
            if not isinstance(input_val, list):
                return False
            # Validate that input items have Responses-specific structure
            if input_val:  # Non-empty list
                first_item = input_val[0]
                if isinstance(first_item, dict):
                    # Responses items have 'type', 'role', 'content' structure
                    # or 'type' like 'function_call', 'function_call_output'
                    has_responses_structure = "type" in first_item or (
                        "role" in first_item and "content" in first_item
                    )
                    if has_responses_structure:
                        return True

        # Look for other distinctive Responses-specific fields
        # These fields are NOT typically in standard OpenAI Chat requests
        responses_specific_fields = {"prompt_cache_key", "include", "store"}
        return any(field in data for field in responses_specific_fields)

    def _resolve_capabilities(
        self, request_data: Any, metadata: dict[str, Any] | None = None
    ) -> CodexClientCapabilities:
        """Resolve client capabilities for downstream translation."""
        return self._capability_resolver.resolve(request_data, metadata)

    def _build_codex_input_items(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        capabilities: CodexClientCapabilities | None = None,
        custom_instruction_sections: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Transform processed messages into Codex Responses `input` array."""
        resolved_capabilities = capabilities or self._resolve_capabilities(request_data)

        return self._request_translator.build_input_items(
            request_data,
            processed_messages,
            effective_model,
            resolved_capabilities,
            custom_instruction_sections=custom_instruction_sections,
        )

    def _build_codex_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        capabilities: CodexClientCapabilities | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Create the request payload and conversation id for Codex Responses API."""
        resolved_capabilities = capabilities or self._resolve_capabilities(request_data)
        conversation_id = str(uuid.uuid4())

        # Scenario 1: Native Responses payload passthrough
        if (
            resolved_capabilities.codex_passthrough
            and self._is_native_responses_payload(request_data)
        ):
            logger.debug("Executing native Codex/Responses payload passthrough.")
            if hasattr(request_data, "model_dump"):
                passthrough_payload = request_data.model_dump(exclude_none=True)
            else:
                passthrough_payload = deepcopy(request_data)

            passthrough_payload.setdefault("model", effective_model)
            passthrough_payload["stream"] = getattr(request_data, "stream", True)

            # Ensure a conversation_id/prompt_cache_key exists, preferring existing ones
            conv_id = (
                passthrough_payload.get("conversation_id")
                or passthrough_payload.get("session_id")
                or passthrough_payload.get("prompt_cache_key")
                or conversation_id
            )
            passthrough_payload["prompt_cache_key"] = conv_id
            return passthrough_payload, conv_id

        # Scenario 2: Build payload from scratch (translation)
        custom_instruction_sections = self._extract_custom_instruction_sections(
            request_data
        )
        input_items = self._build_codex_input_items(
            request_data,
            processed_messages,
            effective_model,
            capabilities=resolved_capabilities,
            custom_instruction_sections=custom_instruction_sections,
        )

        reasoning_payload = getattr(request_data, "reasoning", None)
        reasoning_effort = getattr(request_data, "reasoning_effort", None)
        if not reasoning_payload:
            reasoning_payload = {
                "effort": (reasoning_effort or "medium"),
                "summary": "auto",
            }

        include_items: list[str] = (
            ["reasoning.encrypted_content"] if reasoning_payload else []
        )

        system_prompt = self._resolve_system_prompt(
            request_data,
            resolved_capabilities,
            custom_instruction_sections=custom_instruction_sections,
        )
        payload: dict[str, Any] = {
            "model": effective_model,
            "input": input_items,
            "tools": self._resolve_tool_schema(request_data, resolved_capabilities),
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": reasoning_payload,
            "store": False,
            "stream": True,
            "include": include_items,
            "prompt_cache_key": conversation_id,
        }
        # Include instructions even if empty (empty means use model default)
        if system_prompt:
            payload["instructions"] = self._sanitize_codex_instructions(system_prompt)

        logger.debug(
            "Constructed Codex payload scaffold (protocol=%s, passthrough=%s)",
            resolved_capabilities.protocol,
            resolved_capabilities.codex_passthrough,
        )
        return payload, conversation_id

    def _extract_custom_instruction_sections(self, request_data: Any) -> list[str]:
        """Collect custom instruction snippets supplied by the client request."""
        sections: list[str] = []
        request_prompt = getattr(request_data, "system_prompt", None)
        if isinstance(request_prompt, str) and request_prompt.strip():
            sections.append(request_prompt.strip())

        messages = getattr(request_data, "messages", [])
        for message in messages or []:
            role = getattr(message, "role", None)
            if role is None and isinstance(message, dict):
                role = message.get("role")
            if (role or "").lower() != "system":
                continue
            text = self._message_to_text(message)
            if text.strip():
                sections.append(text.strip())

        extra_body = getattr(request_data, "extra_body", {}) or {}
        extra_prompt = extra_body.get("codex_system_prompt")
        if isinstance(extra_prompt, str) and extra_prompt.strip():
            sections.append(extra_prompt.strip())
        elif isinstance(extra_prompt, list | tuple):
            for part in extra_prompt:
                if isinstance(part, str):
                    text = part.strip()
                    if text:
                        sections.append(text)

        deduplicated: list[str] = []
        seen: set[str] = set()
        for section in sections:
            normalized = section.strip()
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated

    def _render_user_instruction_block(
        self, sections: Sequence[str]
    ) -> dict[str, Any] | None:
        """Render custom instruction sections into a Codex `<user_instructions>` block."""
        sanitized_sections: list[str] = []
        for section in sections:
            if not isinstance(section, str):
                continue
            normalized = section.strip()
            if not normalized:
                continue
            sanitized_sections.append(self._sanitize_codex_instructions(normalized))

        if not sanitized_sections:
            return None

        combined = "\n\n".join(sanitized_sections)
        payload_text = (
            "<user_instructions>\n\n" f"{combined}" "\n\n</user_instructions>"
        )
        return {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": payload_text,
                }
            ],
        }

    def _resolve_system_prompt(
        self,
        request_data: Any,
        capabilities: CodexClientCapabilities,
        custom_instruction_sections: Sequence[str] | None = None,
    ) -> str:
        """Determine the system prompt based on capability settings and request data."""
        prompt_mode = (capabilities.prompt_mode or "codex_default").lower()
        custom_sections = (
            list(custom_instruction_sections)
            if custom_instruction_sections is not None
            else self._extract_custom_instruction_sections(request_data)
        )
        custom_clean = [piece for piece in custom_sections if piece]

        default_prompt_template = self._prompt_settings.get("template")
        default_prompt = (
            default_prompt_template
            if isinstance(default_prompt_template, str)
            and default_prompt_template.strip()
            else self._codex_system_prompt()
        )
        prepend_sections = list(self._prompt_settings.get("prepend", []))
        append_sections = list(self._prompt_settings.get("append", []))
        deduplicate = bool(self._prompt_settings.get("deduplicate", True))
        fallback_to_default = bool(
            self._prompt_settings.get("fallback_to_default", True)
        )

        if prompt_mode == "codex_default":
            combined = [
                *prepend_sections,
                default_prompt,
                *append_sections,
            ]
            result = self._combine_prompt_sections(combined, deduplicate)
            return result if result is not None else ""

        if prompt_mode == "merge_custom":
            combined = [
                *prepend_sections,
                default_prompt,
                *custom_clean,
                *append_sections,
            ]
            result = self._combine_prompt_sections(combined, deduplicate)
            return result if result is not None else ""

        if prompt_mode == "custom_only":
            combined = prepend_sections + custom_clean + append_sections
            merged = self._combine_prompt_sections(combined, deduplicate)
            if merged:
                return merged
            if not fallback_to_default:
                return ""  # Return empty string instead of None
            fallback_combined = [*prepend_sections, default_prompt, *append_sections]
            result = self._combine_prompt_sections(fallback_combined, deduplicate)
            return result if result is not None else ""

        fallback_combined = [*prepend_sections, default_prompt, *append_sections]
        result = self._combine_prompt_sections(fallback_combined, deduplicate)
        return result if result is not None else ""

    def _combine_prompt_sections(
        self, sections: Sequence[str], deduplicate: bool
    ) -> str | None:
        seen: set[str] = set()
        ordered: list[str] = []
        for section in sections:
            if not isinstance(section, str):
                continue
            normalized = section.strip()
            if not normalized:
                continue
            key = normalized if deduplicate else f"{normalized}_{len(ordered)}"
            if deduplicate:
                if key in seen:
                    continue
                seen.add(key)
            # Keep the original section content (preserving trailing newlines)
            ordered.append(section)
        if not ordered:
            return None

        # If only one section, return it as-is
        if len(ordered) == 1:
            return ordered[0]

        # When joining multiple sections, use "\n\n" between them
        return "\n\n".join(ordered)

    @staticmethod
    def _sanitize_codex_instructions(text: str) -> str:
        """Remove or normalize characters that the Codex API rejects in instructions."""
        replacements: dict[str, str] = {
            "\u2010": "-",  # hyphen
            "\u2011": "-",  # non-breaking hyphen
            "\u2012": "-",  # figure dash
            "\u2013": "-",  # en dash
            "\u2014": "--",  # em dash
            "\u2015": "--",  # horizontal bar
            "\u2026": "...",  # ellipsis
            "\u2192": "->",  # arrow
        }
        normalized_parts: list[str] = []
        for char in text:
            if ord(char) < 128:
                normalized_parts.append(char)
            else:
                normalized_parts.append(replacements.get(char, ""))
        return "".join(normalized_parts)

    def _build_codex_headers(self, conversation_id: str) -> dict[str, str]:
        """Construct Codex-specific HTTP headers."""
        headers = self.get_headers() or {}
        headers["OpenAI-Beta"] = "responses=experimental"
        headers["Accept"] = "text/event-stream"
        headers["version"] = self.CODEX_VERSION_HEADER
        headers["originator"] = self.CODEX_ORIGINATOR
        headers["User-Agent"] = self._codex_user_agent()
        headers["conversation_id"] = conversation_id
        headers["session_id"] = conversation_id
        headers["Codex-Task-Type"] = "standard"

        account_id = self._codex_account_id()
        if account_id:
            headers["chatgpt-account-id"] = account_id

        return headers

    def _refresh_codex_headers_auth(
        self, headers: dict[str, str], conversation_id: str
    ) -> None:
        """Update Codex headers in place with latest auth token and session markers."""
        fresh_headers = self.get_headers() or {}
        for key, value in fresh_headers.items():
            headers[key] = value
        # Ensure conversation metadata stays aligned with the current request
        headers["conversation_id"] = conversation_id
        headers["session_id"] = conversation_id

    @staticmethod
    def _extract_status_code_from_payload(
        payload: Mapping[str, Any] | None
    ) -> int | None:
        """Extract an HTTP status code from an error payload, if present."""
        if not isinstance(payload, Mapping):
            return None
        for key in ("status", "status_code", "http_status", "code"):
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, int):
                if 100 <= value <= 599:
                    return value
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.isdigit():
                    numeric = int(stripped)
                    if 100 <= numeric <= 599:
                        return numeric
        return None

    def _should_retry_stream_for_auth_error(
        self, chunk: ProcessedResponse | Any
    ) -> bool:
        """Return True if a streaming chunk indicates an authentication failure."""
        content = getattr(chunk, "content", None)
        if content is None:
            content = chunk

        if not isinstance(content, Mapping):
            return False

        # Primary signal: explicit error payload from translation layer
        error_flag = content.get("error")
        details = content.get("details")

        status = self._extract_status_code_from_payload(
            details if isinstance(details, Mapping) else None
        )
        if status in {401, 403}:
            return True

        # Some payloads stash status inside nested metadata objects
        if isinstance(details, Mapping):
            metadata = details.get("metadata")
            if isinstance(metadata, Mapping):
                status = self._extract_status_code_from_payload(metadata)
                if status in {401, 403}:
                    return True

        # Fall back to heuristics based on codes/messages
        code = None
        if isinstance(details, Mapping):
            code = details.get("code")
        if code is None and isinstance(content, Mapping):
            code = content.get("code")

        def _is_auth_code(value: Any) -> bool:
            if not isinstance(value, str):
                return False
            lowered = value.lower()
            return any(
                token in lowered
                for token in (
                    "auth",
                    "unauthorized",
                    "invalid_token",
                    "invalid_api_key",
                    "token_expired",
                    "access_denied",
                )
            )

        if _is_auth_code(code):
            return True

        for candidate in (error_flag, content.get("message")):
            if isinstance(candidate, str):
                lowered = candidate.lower()
                if "401" in lowered or "403" in lowered or "unauthorized" in lowered:
                    return True
                if "token" in lowered and "expired" in lowered:
                    return True

        return False

    def _stream_retry_delay(self, attempt_index: int) -> float:
        """Return the delay applied before retrying a streaming request."""
        if attempt_index < 0:
            return 0.0
        if not self._stream_retry_backoff:
            return 0.0
        if attempt_index < len(self._stream_retry_backoff):
            return self._stream_retry_backoff[attempt_index]
        return self._stream_retry_backoff[-1]

    def _select_renderer_key(self, capabilities: CodexClientCapabilities) -> str:
        """Map capability preference to a registered renderer key."""
        preferred = (capabilities.tool_text_format or self._renderer_default).strip()
        if not preferred:
            return self._renderer_default
        if preferred.lower() in {"default", "inherit"}:
            return self._renderer_default
        return preferred

    def _clean_xml_from_message(self, content: str) -> str:
        """Remove XML tool tags from message content.

        Args:
            content: Message content containing XML tags

        Returns:
            Content with XML tags removed
        """
        if not content or not isinstance(content, str):
            return content

        # Remove XML tool tags using regex
        # Pattern matches <tag_name>...</tag_name> or <tag_name ... />
        import re
        
        # Get supported tags from XML parser
        supported_tags = []
        if self._kilo_tool_translator and self._kilo_tool_translator._xml_parser:
            from src.connectors._openai_codex_xml_tool_parser import XMLToolParser
            supported_tags = list(XMLToolParser.SUPPORTED_TAGS)
        else:
            # Fallback to common tags
            supported_tags = [
                "read_file", "list_files", "execute_command", "codebase_search",
                "search_files", "use_mcp_tool", "access_mcp_resource",
                "attempt_completion", "ask_followup_question", "search_and_replace",
                "write_to_file", "insert_content", "edit_file"
            ]

        cleaned = content
        for tag in supported_tags:
            # Remove opening and closing tags with content
            pattern = rf"<{tag}(?:\s[^>]*)?>.*?</{tag}>"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)
            
            # Remove self-closing tags
            pattern = rf"<{tag}(?:\s[^>]*)?/>"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # Clean up extra whitespace
        cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)
        cleaned = cleaned.strip()

        return cleaned

    async def _translate_kilo_tools(
        self, message_content: str, session_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        """Parse and translate KiloCode tool invocations.

        Args:
            message_content: Message content containing XML tool invocations
            session_id: Session ID for telemetry

        Returns:
            Dictionary with 'codex_tools', 'proxy_tools', 'mcp_tools' lists
        """
        result: dict[str, list[dict[str, Any]]] = {
            "codex_tools": [],
            "proxy_tools": [],
            "mcp_tools": [],
        }

        if not self._kilo_tool_translator:
            return result

        # Parse XML to find all tool invocations
        try:
            if self._kilo_tool_translator._xml_parser is None:
                from src.connectors._openai_codex_xml_tool_parser import XMLToolParser
                self._kilo_tool_translator._xml_parser = XMLToolParser()

            parsed = self._kilo_tool_translator._xml_parser.parse(message_content)
            if not parsed:
                return result

            # Translate the tool invocation
            start_time = time.time()
            try:
                translation_result = await self._kilo_tool_translator.translate_tool_invocation(
                    parsed.raw_xml, session_id
                )

                if translation_result:
                    tool_name, arguments = translation_result
                    duration_ms = (time.time() - start_time) * 1000

                    # Determine execution mode based on tool name prefix
                    if tool_name.startswith("__proxy_use_mcp_tool") or tool_name.startswith("__proxy_access_mcp_resource"):
                        execution_mode = "mcp"
                        result["mcp_tools"].append({
                            "name": tool_name,
                            "arguments": arguments,
                            "original_xml": parsed.raw_xml,
                            "canonical_name": parsed.canonical_name,
                        })
                    elif tool_name.startswith("__proxy_"):
                        execution_mode = "proxy"
                        result["proxy_tools"].append({
                            "name": tool_name,
                            "arguments": arguments,
                            "original_xml": parsed.raw_xml,
                            "canonical_name": parsed.canonical_name,
                        })
                    else:
                        execution_mode = "codex"
                        result["codex_tools"].append({
                            "name": tool_name,
                            "arguments": arguments,
                            "original_xml": parsed.raw_xml,
                            "canonical_name": parsed.canonical_name,
                        })

                    logger.debug(
                        "Translated tool %s to %s (mode: %s, duration: %.2fms)",
                        parsed.canonical_name,
                        tool_name,
                        execution_mode,
                        duration_ms,
                    )

            except Exception as e:
                # Import TranslationError for type checking
                from src.connectors._openai_codex_compatibility_errors import TranslationError

                # Log translation errors with telemetry
                logger.warning(
                    "Translation error for tool %s: %s",
                    parsed.canonical_name if parsed else "unknown",
                    str(e),
                    exc_info=True,
                )

                # Track error in telemetry if available
                try:
                    from src.connectors._openai_codex_telemetry import get_telemetry
                    telemetry = get_telemetry()
                    if telemetry:
                        duration_ms = (time.time() - start_time) * 1000
                        error_code = e.error_code if isinstance(e, TranslationError) else "UNKNOWN"
                        telemetry.log_error_event(
                            session_id=session_id,
                            error_code=str(error_code),
                            tool_name=parsed.canonical_name if parsed else "unknown",
                            error_message=str(e),
                            original_xml=parsed.raw_xml if parsed else message_content,
                            stack_trace="",
                        )
                except ImportError:
                    pass

        except Exception as e:
            logger.warning(
                "Failed to parse XML tools: %s",
                str(e),
                exc_info=True,
            )

        return result

    def _format_kilo_response(
        self, response: dict[str, Any], tool_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Format response for KiloCode client.

        Args:
            response: Codex response dictionary
            tool_results: List of tool execution results

        Returns:
            Formatted response with tool results merged
        """
        if not tool_results:
            return response

        # Extract content from response
        content = ""
        if "choices" in response and response["choices"]:
            choice = response["choices"][0]
            if "message" in choice:
                content = choice["message"].get("content", "")
            elif "delta" in choice:
                content = choice["delta"].get("content", "")

        # Prepend tool results to content
        tool_results_text = "\n\n".join(
            result["result"] for result in tool_results if result.get("result")
        )

        if tool_results_text:
            if content:
                merged_content = f"{tool_results_text}\n\n{content}"
            else:
                merged_content = tool_results_text

            # Update response with merged content
            if "choices" in response and response["choices"]:
                choice = response["choices"][0]
                if "message" in choice:
                    choice["message"]["content"] = merged_content
                elif "delta" in choice:
                    choice["delta"]["content"] = merged_content

        return response

    async def _format_kilo_stream_response(
        self, stream: AsyncIterator[Any], tool_results: list[dict[str, Any]]
    ) -> AsyncIterator[Any]:
        """Format streaming response for KiloCode client.

        Args:
            stream: Async iterator of response chunks
            tool_results: List of tool execution results

        Yields:
            Formatted response chunks with tool results prepended
        """
        # First, yield tool results as initial chunks
        if tool_results:
            tool_results_text = "\n\n".join(
                result["result"] for result in tool_results if result.get("result")
            )

            if tool_results_text:
                # Create a chunk with tool results
                yield {
                    "choices": [
                        {
                            "delta": {
                                "content": tool_results_text + "\n\n",
                                "role": "assistant",
                            },
                            "index": 0,
                            "finish_reason": None,
                        }
                    ],
                    "created": int(time.time()),
                    "model": "gpt-4",
                    "object": "chat.completion.chunk",
                }

        # Then yield all chunks from the original stream
        async for chunk in stream:
            yield chunk

    async def _execute_proxy_tool(
        self, tool_name: str, arguments: dict[str, Any], session_id: str
    ) -> dict[str, Any]:
        """Execute a proxy-side tool using UniversalToolExecutor.

        Args:
            tool_name: Tool name (with __proxy_ prefix)
            arguments: Tool arguments
            session_id: Session ID for telemetry

        Returns:
            Dictionary with 'success', 'result', 'error' keys
        """
        start_time = time.time()
        result: dict[str, Any] = {
            "success": False,
            "result": "",
            "error": None,
        }

        try:
            # Handle conversation control tools specially
            if tool_name in ("__proxy_attempt_completion", "__proxy_ask_followup_question"):
                if self._kilo_tool_translator:
                    formatted_result = await self._kilo_tool_translator.handle_conversation_control(
                        tool_name, arguments, session_id
                    )
                    result["success"] = True
                    result["result"] = formatted_result
                else:
                    result["error"] = "KiloToolTranslator not available"
                    logger.error("Cannot handle conversation control: translator not available")
            else:
                # Execute using UniversalToolExecutor
                if not self._universal_executor:
                    # Lazy initialize executor
                    self._universal_executor = await self._get_universal_executor()

                if not self._universal_executor:
                    result["error"] = "UniversalToolExecutor not available"
                    logger.error("Cannot execute proxy tool: executor not available")
                else:
                    # Remove __proxy_ prefix for execution
                    actual_tool_name = tool_name.replace("__proxy_", "")
                    
                    # Execute the tool
                    exec_result = await self._universal_executor.execute_tool(
                        actual_tool_name, arguments
                    )

                    # Format result using KiloToolTranslator
                    if self._kilo_tool_translator:
                        formatted_result = self._kilo_tool_translator.format_tool_result(
                            actual_tool_name, exec_result
                        )
                        result["success"] = True
                        result["result"] = formatted_result
                    else:
                        result["success"] = True
                        result["result"] = str(exec_result)

        except Exception as e:
            result["error"] = str(e)
            logger.error(
                "Proxy tool execution failed for %s: %s",
                tool_name,
                str(e),
                exc_info=True,
            )

        # Track execution duration for telemetry
        duration_ms = (time.time() - start_time) * 1000
        logger.debug(
            "Proxy tool %s executed in %.2fms (success: %s)",
            tool_name,
            duration_ms,
            result["success"],
        )

        # Format error result if execution failed
        if not result["success"] and result["error"]:
            actual_tool_name = tool_name.replace("__proxy_", "")
            result["result"] = f"[{actual_tool_name}] Error: {result['error']}"

        return result

    async def _execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any], session_id: str
    ) -> dict[str, Any]:
        """Execute an MCP tool via MCP bridge.

        Args:
            tool_name: Tool name (with __proxy_ prefix)
            arguments: Tool arguments containing tool_name and tool_arguments
            session_id: Session ID for telemetry

        Returns:
            Dictionary with 'success', 'result', 'error' keys

        Raises:
            TranslationError: If MCP execution fails
        """
        from src.connectors._openai_codex_compatibility_errors import (
            CompatibilityErrorCode,
            TranslationError,
        )

        start_time = time.time()
        result: dict[str, Any] = {
            "success": False,
            "result": "",
            "error": None,
        }

        # Extract MCP tool name from arguments
        mcp_tool_name = arguments.get("tool_name", "")
        if not mcp_tool_name or not isinstance(mcp_tool_name, str):
            error = TranslationError(
                message="Missing or invalid 'tool_name' parameter in MCP tool invocation",
                tool_name=tool_name,
                error_code=CompatibilityErrorCode.INVALID_TOOL_ARGUMENTS,
                session_id=session_id,
                details={"missing_parameters": ["tool_name"]},
            )
            logger.error(str(error))
            result["error"] = str(error)
            return result

        # Extract MCP tool parameters
        mcp_parameters = arguments.get("tool_arguments", {})
        if not isinstance(mcp_parameters, dict):
            mcp_parameters = {}

        # Log MCP tool execution start event
        logger.info(
            "Starting MCP tool execution: tool=%s, session=%s",
            mcp_tool_name,
            session_id,
        )

        try:
            # Check if MCP client is available
            mcp_client = getattr(self, "_mcp_client", None)
            if not mcp_client:
                raise TranslationError(
                    message="MCP server not available",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_UNAVAILABLE,
                    session_id=session_id,
                )

            # Connect to MCP server if not already connected
            try:
                if hasattr(mcp_client, "is_connected") and not mcp_client.is_connected():
                    logger.info("MCP client not connected, attempting to connect...")
                    if hasattr(mcp_client, "connect"):
                        await mcp_client.connect()
                        logger.info("Successfully connected to MCP server")
            except Exception as conn_error:
                logger.error(
                    "Failed to connect to MCP server: %s",
                    str(conn_error),
                    exc_info=True,
                )
                raise TranslationError(
                    message=f"Failed to connect to MCP server: {str(conn_error)}",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_UNAVAILABLE,
                    session_id=session_id,
                    details={"connection_error": str(conn_error)},
                )

            # Translate parameters if needed (schema translation)
            if self._kilo_tool_translator and hasattr(self._kilo_tool_translator, "_translate_mcp_parameters"):
                # Get MCP tool schema if available
                mcp_schema = None
                if hasattr(mcp_client, "get_tool_schema"):
                    try:
                        mcp_schema = await mcp_client.get_tool_schema(mcp_tool_name)
                    except Exception as e:
                        logger.debug("Could not retrieve MCP tool schema: %s", str(e))

                # Translate parameters
                if mcp_schema:
                    try:
                        mcp_parameters = self._kilo_tool_translator._translate_mcp_parameters(
                            mcp_parameters, mcp_schema
                        )
                    except Exception as e:
                        logger.warning("Parameter translation failed, using original parameters: %s", str(e))

            # Log MCP communication event
            logger.debug(
                "Sending MCP tool request: tool=%s, parameters=%s",
                mcp_tool_name,
                mcp_parameters,
            )

            # Send tool execution request with timeout
            try:
                mcp_result = await asyncio.wait_for(
                    mcp_client.call_tool(mcp_tool_name, mcp_parameters),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                raise TranslationError(
                    message=f"Execution timed out after 30s",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_TIMEOUT,
                    session_id=session_id,
                )
            except AttributeError as e:
                # MCP tool not found
                raise TranslationError(
                    message=f"Tool {mcp_tool_name} not found",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_TOOL_NOT_FOUND,
                    session_id=session_id,
                    details={"mcp_error": str(e)},
                )
            except Exception as e:
                # MCP execution error
                raise TranslationError(
                    message=f"MCP execution failed: {str(e)}",
                    tool_name=mcp_tool_name,
                    error_code=CompatibilityErrorCode.MCP_EXECUTION_FAILED,
                    session_id=session_id,
                    details={"mcp_error": str(e)},
                )

            # Log MCP response received
            logger.debug(
                "Received MCP tool response: tool=%s, result_type=%s",
                mcp_tool_name,
                type(mcp_result).__name__,
            )

            # Format MCP result for KiloCode
            if self._kilo_tool_translator:
                formatted_result = self._kilo_tool_translator.format_tool_result(
                    mcp_tool_name, mcp_result
                )
                result["success"] = True
                result["result"] = formatted_result
            else:
                result["success"] = True
                result["result"] = str(mcp_result)

        except TranslationError as e:
            # Log error with telemetry
            result["error"] = str(e)
            logger.error(
                "MCP tool execution failed [%s]: %s (tool: %s, session: %s)",
                e.error_code,
                str(e),
                mcp_tool_name,
                session_id,
                exc_info=True,
            )

            # Track error in telemetry
            try:
                from src.connectors._openai_codex_telemetry import get_telemetry
                telemetry = get_telemetry()
                if telemetry:
                    duration_ms = (time.time() - start_time) * 1000
                    telemetry.log_error_event(
                        session_id=session_id,
                        error_code=str(e.error_code),
                        tool_name=mcp_tool_name,
                        error_message=str(e),
                        original_xml=arguments.get("original_xml", ""),
                        stack_trace="",
                    )
            except ImportError:
                pass

        except Exception as e:
            # Unexpected error
            result["error"] = str(e)
            logger.error(
                "Unexpected error during MCP tool execution: %s (tool: %s, session: %s)",
                str(e),
                mcp_tool_name,
                session_id,
                exc_info=True,
            )

        # Track execution duration for telemetry
        duration_ms = (time.time() - start_time) * 1000
        logger.debug(
            "MCP tool %s executed in %.2fms (success: %s)",
            mcp_tool_name,
            duration_ms,
            result["success"],
        )

        # Log MCP tool execution end event
        try:
            from src.connectors._openai_codex_telemetry import get_telemetry
            telemetry = get_telemetry()
            if telemetry and result["success"]:
                telemetry.log_translation_event(
                    session_id=session_id,
                    tool_name=mcp_tool_name,
                    original_xml=arguments.get("original_xml", ""),
                    translated_tool=mcp_tool_name,
                    execution_mode="mcp",
                    duration_ms=duration_ms,
                    success=True,
                )
        except ImportError:
            pass

        # Format error result if execution failed
        if not result["success"] and result["error"]:
            result["result"] = f"[{mcp_tool_name}] Error: {result['error']}"

        return result

    async def _call_codex_responses_api(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        domain_request: Any,
    ) -> Any:
        """Call the Codex-specific Responses API endpoint."""
        capabilities = self._resolve_capabilities(request_data)

        # Store capabilities in the processing context if available
        if hasattr(domain_request, "processing_context"):
            if domain_request.processing_context is None:
                domain_request.processing_context = {}
            domain_request.processing_context["codex_capabilities"] = (
                capabilities.to_dict()
            )
            domain_request.processing_context["bypass_tool_call_reactor"] = (
                capabilities.bypass_tool_call_reactor
            )
            domain_request.processing_context["tool_text_format"] = (
                capabilities.tool_text_format
            )

        # Detect KiloCode client and activate compatibility layer if enabled
        session_id = getattr(domain_request, "session_id", None) or str(uuid.uuid4())
        is_kilocode = False
        if self._compatibility_layer_enabled and self._session_detector:
            # Extract metadata for detection
            metadata = None
            if hasattr(domain_request, "metadata"):
                metadata = domain_request.metadata
            elif hasattr(request_data, "metadata"):
                metadata = request_data.metadata

            # Perform detection
            detection_result = await self._session_detector.detect(
                request_data=request_data,
                metadata=metadata,
                session_id=session_id,
                backend=self.backend_type,
            )
            is_kilocode = detection_result.is_kilocode

            # Store detection result in processing context
            if hasattr(domain_request, "processing_context"):
                if domain_request.processing_context is None:
                    domain_request.processing_context = {}
                domain_request.processing_context["is_kilocode_client"] = is_kilocode
                domain_request.processing_context["kilocode_detection_method"] = (
                    detection_result.detection_method
                )

            if is_kilocode:
                logger.info(
                    "KiloCode client detected for session %s (method: %s, confidence: %.2f)",
                    session_id,
                    detection_result.detection_method,
                    detection_result.confidence,
                )

        # Parse and translate XML tool invocations for KiloCode clients
        translated_tools: dict[str, list[dict[str, Any]]] = {
            "codex_tools": [],
            "proxy_tools": [],
            "mcp_tools": [],
        }
        tool_results: list[dict[str, Any]] = []
        if is_kilocode and self._kilo_tool_translator:
            # Extract message content and check for XML tags
            for message in processed_messages:
                content = message.get("content", "")
                if isinstance(content, str) and "<" in content and ">" in content:
                    # Translate tools using the new method
                    try:
                        tools = await self._translate_kilo_tools(content, session_id)
                        # Merge results
                        translated_tools["codex_tools"].extend(tools["codex_tools"])
                        translated_tools["proxy_tools"].extend(tools["proxy_tools"])
                        translated_tools["mcp_tools"].extend(tools["mcp_tools"])
                    except Exception as e:
                        logger.warning(
                            "Failed to translate XML tools in message: %s",
                            str(e),
                            exc_info=True
                        )

            # Execute proxy-side tools
            for tool in translated_tools["proxy_tools"]:
                try:
                    result = await self._execute_proxy_tool(
                        tool["name"],
                        tool["arguments"],
                        session_id
                    )
                    tool_results.append(result)
                    logger.debug(
                        "Executed proxy tool %s: success=%s",
                        tool["name"],
                        result["success"]
                    )
                except Exception as e:
                    logger.error(
                        "Failed to execute proxy tool %s: %s",
                        tool["name"],
                        str(e),
                        exc_info=True
                    )
                    # Add error result
                    actual_tool_name = tool["name"].replace("__proxy_", "")
                    tool_results.append({
                        "success": False,
                        "result": f"[{actual_tool_name}] Error: {str(e)}",
                        "error": str(e)
                    })

            # Execute MCP tools
            for tool in translated_tools["mcp_tools"]:
                try:
                    result = await self._execute_mcp_tool(
                        tool["name"],
                        tool["arguments"],
                        session_id
                    )
                    tool_results.append(result)
                    logger.debug(
                        "Executed MCP tool %s: success=%s",
                        tool["name"],
                        result["success"]
                    )
                except Exception as e:
                    logger.error(
                        "Failed to execute MCP tool %s: %s",
                        tool["name"],
                        str(e),
                        exc_info=True
                    )
                    # Add error result
                    mcp_tool_name = tool["arguments"].get("tool_name", "unknown")
                    tool_results.append({
                        "success": False,
                        "result": f"[{mcp_tool_name}] Error: {str(e)}",
                        "error": str(e)
                    })

            # Clean XML tags from messages before sending to Codex
            if translated_tools["codex_tools"] or translated_tools["proxy_tools"] or translated_tools["mcp_tools"]:
                for message in processed_messages:
                    content = message.get("content", "")
                    if isinstance(content, str) and "<" in content and ">" in content:
                        cleaned_content = self._clean_xml_from_message(content)
                        if cleaned_content != content:
                            message["content"] = cleaned_content
                            logger.debug(
                                "Cleaned XML from message (original: %d bytes, cleaned: %d bytes)",
                                len(content),
                                len(cleaned_content)
                            )

        payload, conversation_id = self._build_codex_payload(
            request_data,
            processed_messages,
            effective_model,
            capabilities=capabilities,
        )

        # Add translated Codex-side tools to payload
        if is_kilocode and translated_tools["codex_tools"]:
            # Ensure tools array exists in payload
            if "tools" not in payload:
                payload["tools"] = []
            
            # Add each translated tool to the payload
            for tool in translated_tools["codex_tools"]:
                tool_name = tool["name"]
                tool_args = tool["arguments"]
                
                # Create tool schema for Codex
                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "parameters": tool_args,
                    }
                }
                
                # Check if tool already exists in payload
                existing_tool = next(
                    (t for t in payload["tools"] if t.get("function", {}).get("name") == tool_name),
                    None
                )
                
                if not existing_tool:
                    payload["tools"].append(tool_schema)
                    logger.debug(
                        "Added Codex-side tool %s to payload",
                        tool_name
                    )
        if logger.isEnabledFor(logging.DEBUG):
            try:
                logger.debug(
                    "Codex payload input count=%s first_entries=%s tail_entries=%s",
                    len(payload.get("input", [])),
                    json.dumps(payload.get("input", [])[:6])[:600],
                    json.dumps(payload.get("input", [])[-6:])[:600],
                )
            except Exception:
                logger.debug("Codex payload input=<unserializable>")
        headers = self._build_codex_headers(conversation_id)
        url = "https://chatgpt.com/backend-api/codex/responses"

        renderer_key = self._select_renderer_key(capabilities)
        session_id = getattr(domain_request, "session_id", None) or conversation_id
        stream_val = getattr(request_data, "stream", False)

        async def _perform_request(
            request_payload: dict[str, Any],
            request_headers: dict[str, str],
            request_session_id: str,
            is_streaming_request: bool,
        ) -> Any:
            if is_streaming_request:
                headers_holder: dict[str, str] = {}
                current_cancel: list[Callable[[], Awaitable[None]] | None] = [None]

                async def cancel_active_stream() -> None:
                    cancel_cb = current_cancel[0]
                    if cancel_cb is not None:
                        await cancel_cb()

                async def _rendered_iterator() -> AsyncIterator[Any]:
                    attempts_used = 0
                    max_retries = max(0, self._stream_retry_limit)
                    current_headers = dict(request_headers)
                    while True:
                        try:
                            with OverrideRenderer(renderer_key):
                                stream_handle = await self._handle_streaming_response(
                                    url,
                                    request_payload,
                                    current_headers,
                                    request_session_id,
                                    "responses",
                                )
                        except HTTPException as exc:
                            if exc.status_code == 401:
                                if attempts_used >= max_retries:
                                    self._degrade(
                                        [
                                            "Streaming authentication failed during initial handshake after "
                                            f"{attempts_used} retry attempts (limit {max_retries})."
                                        ]
                                    )
                                    raise HTTPException(
                                        status_code=401,
                                        detail={
                                            "error": "openai_codex_stream_auth_failed",
                                            "message": "Codex streaming request failed authentication during handshake and could not be recovered.",
                                            "details": {
                                                "backend": self.name,
                                                "attempts": attempts_used,
                                                "max_retries": max_retries,
                                            },
                                        },
                                    )
                                refreshed = await self._refresh_access_token()
                                if not refreshed:
                                    self._degrade(
                                        [
                                            "Streaming authentication failed during initial handshake; token refresh unsuccessful."
                                        ]
                                    )
                                    raise HTTPException(
                                        status_code=401,
                                        detail={
                                            "error": "openai_codex_stream_auth_failed",
                                            "message": "Codex streaming request failed authentication during handshake and could not be recovered.",
                                            "details": {
                                                "backend": self.name,
                                                "attempts": attempts_used,
                                                "max_retries": max_retries,
                                            },
                                        },
                                    )
                                delay = self._stream_retry_delay(attempts_used)
                                attempts_used += 1
                                if delay > 0:
                                    await asyncio.sleep(delay)
                                self._refresh_codex_headers_auth(
                                    current_headers, conversation_id
                                )
                                continue
                            raise
                        current_cancel[0] = stream_handle.cancel_callback
                        headers_holder.clear()
                        try:
                            headers_holder.update(dict(stream_handle.headers or {}))
                        except Exception:
                            headers_holder.clear()

                        restart_stream = False
                        with OverrideRenderer(renderer_key):
                            async for processed_chunk in stream_handle.iterator:
                                if self._should_retry_stream_for_auth_error(
                                    processed_chunk
                                ):
                                    restart_stream = True
                                    logger.info(
                                        "Codex streaming chunk reported authentication failure; attempting token refresh."
                                    )
                                    break
                                yield processed_chunk

                        if restart_stream:
                            if stream_handle.cancel_callback is not None:
                                with contextlib.suppress(Exception):
                                    await stream_handle.cancel_callback()

                            if attempts_used >= max_retries:
                                self._degrade(
                                    [
                                        "Streaming authentication failed after retries were exhausted "
                                        f"({attempts_used} attempts, limit {max_retries})."
                                    ]
                                )
                                raise HTTPException(
                                    status_code=401,
                                    detail={
                                        "error": "openai_codex_stream_auth_failed",
                                        "message": "Codex streaming request failed authentication and could not be recovered.",
                                        "details": {
                                            "backend": self.name,
                                            "attempts": attempts_used,
                                            "max_retries": max_retries,
                                        },
                                    },
                                )

                            refreshed = await self._refresh_access_token()
                            if not refreshed:
                                self._degrade(
                                    [
                                        "Streaming authentication failed after token refresh."
                                    ]
                                )
                                raise HTTPException(
                                    status_code=401,
                                    detail={
                                        "error": "openai_codex_stream_auth_failed",
                                        "message": "Codex streaming request failed authentication and could not be recovered.",
                                        "details": {
                                            "backend": self.name,
                                            "attempts": attempts_used,
                                            "max_retries": max_retries,
                                        },
                                    },
                                )

                            delay = self._stream_retry_delay(attempts_used)
                            attempts_used += 1
                            if delay > 0:
                                await asyncio.sleep(delay)
                            self._refresh_codex_headers_auth(
                                current_headers, conversation_id
                            )
                            continue

                        current_cancel[0] = None
                        return

                return StreamingResponseEnvelope(
                    content=_rendered_iterator(),
                    media_type="text/event-stream",
                    headers=headers_holder,
                    cancel_callback=cancel_active_stream,
                )
            else:
                with OverrideRenderer(renderer_key):
                    return await self._handle_non_streaming_response(
                        url,
                        request_payload,
                        request_headers,
                        request_session_id,
                    )

        for attempt in range(2):
            try:
                response = await _perform_request(payload, headers, session_id, stream_val)
                
                # Format response for KiloCode clients if needed
                if is_kilocode and tool_results:
                    if stream_val:
                        # For streaming responses, wrap the iterator
                        if hasattr(response, "content") and hasattr(response.content, "__aiter__"):
                            formatted_stream = self._format_kilo_stream_response(
                                response.content, tool_results
                            )
                            # Create new envelope with formatted stream
                            return StreamingResponseEnvelope(
                                content=formatted_stream,
                                media_type=response.media_type if hasattr(response, "media_type") else "text/event-stream",
                                headers=response.headers if hasattr(response, "headers") else {},
                                cancel_callback=response.cancel_callback if hasattr(response, "cancel_callback") else None,
                            )
                    else:
                        # For non-streaming responses, format the response dict
                        if isinstance(response, dict):
                            response = self._format_kilo_response(response, tool_results)
                
                return response
            except httpx.HTTPStatusError as exc:
                try:
                    body = exc.response.json()
                except json.JSONDecodeError:
                    body = exc.response.text
                logger.warning(
                    "Codex API request failed with status %s: %s",
                    exc.response.status_code,
                    body,
                )
                # Re-raise as a standard HTTPException to be handled by the app
                raise HTTPException(status_code=exc.response.status_code, detail=body)
            except HTTPException as exc:
                if exc.status_code == 401 and attempt == 0:
                    # Only refresh token - reuse same payload and conversation_id to maintain session continuity
                    refreshed = await self._refresh_access_token()
                    if refreshed:
                        # No need to rebuild payload or conversation_id - just update headers with new token
                        self._refresh_codex_headers_auth(headers, conversation_id)
                        continue
                raise

        # Should never reach here because loop either returns or raises.
        raise RuntimeError("Unexpected fallthrough in Codex response handling.")

    async def _refresh_access_token(self) -> bool:
        """Attempt to refresh the Codex OAuth access token using the stored refresh token."""
        async with self._token_refresh_lock:
            logger.info(
                "Attempting to refresh OpenAI Codex access token after authentication failure."
            )
            # CRITICAL: Always reload credentials inside the lock to avoid race conditions
            # This ensures stale tokens aren't used by parallel coroutines
            await self._load_auth(force_reload=True)
            if not self._auth_credentials:
                logger.warning(
                    "Cannot refresh OpenAI Codex token: credentials not loaded."
                )
                return False

            tokens = self._auth_credentials.get("tokens")
            if not isinstance(tokens, dict):
                logger.warning(
                    "Cannot refresh OpenAI Codex token: tokens payload missing in auth.json."
                )
                return False

            refresh_token = tokens.get("refresh_token")
            if not isinstance(refresh_token, str) or not refresh_token:
                logger.warning(
                    "Cannot refresh OpenAI Codex token: refresh_token not present in auth.json."
                )
                return False

            payload = {
                "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            }

            try:
                response = await self.client.post(
                    "https://auth.openai.com/oauth/token",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=15.0,
                )
            except httpx.HTTPError as exc:
                logger.warning("Failed to refresh OpenAI Codex token: %s", exc)
                return False

            if response.status_code >= 400:
                body = response.text
                logger.warning(
                    "OpenAI Codex token refresh failed with status %s: %s",
                    response.status_code,
                    body,
                )
                return False

            try:
                token_response = response.json()
            except Exception as exc:
                logger.warning("Failed to parse OAuth token refresh response: %s", exc)
                return False

            access_token = token_response.get("access_token")
            new_refresh_token = token_response.get("refresh_token") or refresh_token
            id_token = token_response.get("id_token")
            if not isinstance(access_token, str) or not access_token:
                logger.warning("OAuth token refresh response missing access_token.")
                return False

            updated_credentials = deepcopy(self._auth_credentials)
            updated_tokens = updated_credentials.setdefault("tokens", {})
            updated_tokens["access_token"] = access_token
            updated_tokens["refresh_token"] = new_refresh_token
            if isinstance(id_token, str) and id_token:
                updated_tokens["id_token"] = id_token
            if isinstance(self._auth_path, Path):
                updated_credentials["last_refresh"] = datetime.now(
                    timezone.utc
                ).isoformat()

                # Use atomic write pattern to prevent file corruption
                try:
                    # Create temp file in same directory for atomic os.replace()
                    temp_fd, temp_path = tempfile.mkstemp(
                        dir=self._auth_path.parent,
                        prefix=".auth_",
                        suffix=".json.tmp",
                        text=True,
                    )
                    try:
                        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                            json.dump(updated_credentials, f, indent=2)
                            f.write("\n")
                            f.flush()
                            os.fsync(f.fileno())  # Ensure written to disk
                        # Atomic replacement (cross-platform)
                        os.replace(temp_path, self._auth_path)
                    except Exception:
                        # Clean up temp file on error
                        import contextlib

                        with contextlib.suppress(Exception):
                            os.unlink(temp_path)
                        raise
                except Exception as exc:
                    logger.warning(
                        "Failed to persist refreshed OAuth credentials: %s", exc
                    )
                    return False
            else:
                logger.warning(
                    "Cannot persist refreshed OAuth credentials: auth path unknown."
                )
                return False

            self._auth_credentials = updated_credentials
            await self._load_auth(force_reload=True)
            logger.info("Successfully refreshed OpenAI Codex access token.")
            return True

    # -----------------------------
    # Health Tracking API (stale token handling pattern)
    # -----------------------------
    def is_backend_functional(self) -> bool:
        """Return True if the backend is functional and ready to serve requests."""
        return self.is_functional and not self._initialization_failed

    def get_validation_errors(self) -> list[str]:
        """Return list of validation errors encountered during initialization or runtime."""
        return self._credential_validation_errors.copy()

    def _fail_init(self, errors: list[str]) -> None:
        """Mark initialization as failed with given errors."""
        self._initialization_failed = True
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.error(f"OpenAI Codex initialization failed: {'; '.join(errors)}")

    def _degrade(self, errors: list[str]) -> None:
        """Mark backend as degraded due to runtime validation failures."""
        self.is_functional = False
        self._credential_validation_errors = errors
        logger.warning(f"OpenAI Codex backend degraded: {'; '.join(errors)}")

    def _recover(self) -> None:
        """Mark backend as recovered after successful validation."""
        self.is_functional = True
        self._credential_validation_errors = []
        self._last_validation_time = time.time()
        logger.info("OpenAI Codex backend recovered")

    # -----------------------------
    # Validation methods (stale token handling pattern)
    # -----------------------------
    def _validate_credentials_file_exists(self) -> tuple[bool, list[str]]:
        """Validate that credentials file exists and is readable."""
        errors = []

        auth_path = self._discover_auth_path()
        if auth_path is None:
            errors.append("OAuth credentials file not found in any default location")
            return False, errors

        if not auth_path.exists():
            errors.append(f"OAuth credentials file does not exist: {auth_path}")
            return False, errors

        if not auth_path.is_file():
            errors.append(f"OAuth credentials path is not a file: {auth_path}")
            return False, errors

        try:
            with open(auth_path, encoding="utf-8") as f:
                json.load(f)
        except json.JSONDecodeError as e:
            errors.append(f"OAuth credentials file contains invalid JSON: {e}")
            return False, errors
        except PermissionError:
            errors.append(f"No permission to read OAuth credentials file: {auth_path}")
            return False, errors
        except Exception as e:
            errors.append(f"Error reading OAuth credentials file: {e}")
            return False, errors

        return True, errors

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Validate OAuth credentials structure and content."""
        errors = []

        if not isinstance(credentials, dict):
            errors.append("OAuth credentials must be a JSON object")
            return False, errors

        # Check for tokens.access_token or OPENAI_API_KEY
        access_token = None
        tokens = credentials.get("tokens")
        if isinstance(tokens, dict):
            tok = tokens.get("access_token")
            if isinstance(tok, str) and tok.strip():
                access_token = tok

        api_key = credentials.get("OPENAI_API_KEY")
        if not access_token and not (isinstance(api_key, str) and api_key.strip()):
            errors.append(
                "OAuth credentials missing required 'tokens.access_token' or 'OPENAI_API_KEY' field"
            )
            return False, errors

        return True, errors

    def _validate_runtime_credentials(self) -> tuple[bool, list[str]]:
        """Validate credentials at runtime with throttling."""
        # Simple throttling: only validate once per 30 seconds
        current_time = time.time()
        if current_time - self._last_validation_time < 30:
            return True, []

        # Validate file existence and structure
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            return False, errors

        if self._auth_credentials is not None:
            ok, struct_errors = self._validate_credentials_structure(
                self._auth_credentials
            )
            if not ok:
                errors.extend(struct_errors)
                return False, errors
        else:
            errors.append("OAuth credentials not loaded in memory")
            return False, errors

        self._last_validation_time = current_time
        return True, errors

    # -----------------------------
    # File watching methods (stale token handling pattern)
    # -----------------------------
    def _start_file_watching(self) -> None:
        """Start watching the credentials file for changes."""
        if self._auth_path is None or self._file_observer is not None:
            return

        try:
            self._file_observer = Observer()
            handler = OpenAICredentialsFileHandler(self)
            watch_dir = self._auth_path.parent
            self._file_observer.schedule(handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            logger.debug(
                f"Started watching OpenAI Codex credentials directory: {watch_dir}"
            )
        except Exception as e:
            logger.warning(
                f"Failed to start file watching for OpenAI Codex credentials: {e}"
            )

    def _stop_file_watching(self) -> None:
        """Stop watching the credentials file for changes."""
        if self._file_observer is not None:
            try:
                self._file_observer.stop()
                self._file_observer.join(timeout=1.0)
            except Exception as e:
                logger.debug(f"Error stopping OpenAI Codex file watcher: {e}")
            finally:
                self._file_observer = None

    def _schedule_credentials_reload(self) -> None:
        """Schedule an asynchronous reload of credentials.

        This method is called when the file system watcher detects a change to the
        auth.json file. It forces a reload of credentials bypassing the cache
        to ensure the latest token is loaded even if the file timestamp didn't change.
        """
        # Use threading.Event for thread-safe coordination
        if self._reload_scheduling_event.is_set():
            # Reload already in progress
            return

        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return
            self._reload_scheduling_event.set()

        async def reload_task() -> None:
            try:
                logger.debug("Reloading OpenAI Codex credentials due to file change")
                # Use force_reload=True to bypass cache
                try:
                    loaded = await self._load_auth(force_reload=True)
                except TypeError:
                    loaded = await self._load_auth()
                if loaded:
                    if self._auth_credentials is not None:
                        ok, errors = self._validate_credentials_structure(
                            self._auth_credentials
                        )
                        if ok:
                            self._recover()
                        else:
                            self._degrade(errors)
                    else:
                        self._degrade(
                            ["Failed to load credentials despite successful file read"]
                        )
                else:
                    self._degrade(["Failed to reload credentials from file"])
            except Exception as e:
                logger.error(f"Error during OpenAI Codex credentials reload: {e}")
                self._degrade([f"Credentials reload failed: {e}"])

        loop = self._event_loop
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning(
                    "Cannot schedule credentials reload: no running event loop available."
                )
                self._reload_scheduling_event.clear()
                return
            self._event_loop = loop

        if loop.is_closed():
            logger.warning("Cannot schedule credentials reload: event loop is closed.")
            self._reload_scheduling_event.clear()
            return

        def _clear(_: asyncio.Future[Any]) -> None:
            with self._reload_task_lock:
                self._pending_reload_task = None
            self._reload_scheduling_event.clear()

        def _assign_task(task: asyncio.Future[None]) -> None:
            task.add_done_callback(_clear)
            with self._reload_task_lock:
                self._pending_reload_task = task

        try:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is loop:
                task = loop.create_task(reload_task())
                _assign_task(task)
                return

            def schedule_task() -> None:
                try:
                    task = loop.create_task(reload_task())
                    _assign_task(task)
                except Exception as exc:
                    logger.warning(
                        "Failed to schedule OpenAI Codex credentials reload: %s", exc
                    )
                    self._reload_scheduling_event.clear()

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI Codex credentials reload: %s", exc
            )
            self._reload_scheduling_event.clear()

    def _default_auth_paths(self) -> list[Path]:
        paths: list[Path] = []
        userprofile = os.getenv("USERPROFILE")
        if userprofile:
            paths.append(Path(userprofile) / ".codex" / "auth.json")
        # Cross-platform default
        paths.append(Path.home() / ".codex" / "auth.json")
        return paths

    def _discover_auth_path(self) -> Path | None:
        if self._oauth_dir_override is not None:
            return self._oauth_dir_override / "auth.json"
        for p in self._default_auth_paths():
            if p.exists():
                return p
        return None

    async def _load_auth(self, force_reload: bool = False) -> bool:
        """Load OAuth credentials from auth.json file.

        Args:
            force_reload: If True, bypass cache and force reload from file even if timestamp unchanged

        Returns:
            bool: True if credentials loaded successfully, False otherwise
        """
        auth_path = self._discover_auth_path()
        if auth_path is None:
            logger.warning("OpenAI Codex auth.json not found in default locations")
            return False

        self._auth_path = auth_path
        try:
            # Check if file has been modified since last load (unless force_reload is True)
            if not force_reload:
                try:
                    mtime = auth_path.stat().st_mtime
                    if mtime == self._last_modified and self.api_key:
                        logger.debug(
                            "OpenAI Codex credentials file not modified, using cached."
                        )
                        return True
                except OSError:
                    pass

            # Update last modified time
            try:
                mtime = auth_path.stat().st_mtime
                self._last_modified = mtime
            except OSError:
                pass

            with open(auth_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            token: str | None = None
            # Prefer ChatGPT OAuth access token
            tokens = data.get("tokens")
            if isinstance(tokens, dict):
                tok = tokens.get("access_token")
                if isinstance(tok, str) and tok:
                    token = tok
            # Fallback to OPENAI_API_KEY if present
            if not token:
                api_key = data.get("OPENAI_API_KEY")
                if isinstance(api_key, str) and api_key:
                    token = api_key

            if not token:
                logger.warning(
                    "OpenAI Codex auth.json missing tokens.access_token and OPENAI_API_KEY"
                )
                return False

            # Set as API key for parent header logic
            self.api_key = token
            # Store credentials for validation
            self._auth_credentials = data
            log_msg = "Successfully loaded OpenAI Codex credentials"
            if force_reload:
                log_msg += " (force reload)"
            logger.info(log_msg + ".")
            return True
        except json.JSONDecodeError as e:
            logger.error("Malformed auth.json for OpenAI Codex: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error(
                "Failed to load OpenAI Codex credentials: %s", e, exc_info=True
            )
            return False

    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend with enhanced validation using stale token handling pattern."""
        logger.info("Initializing OpenAI Codex backend with enhanced validation.")

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        # Allow base URL override
        base = kwargs.get("openai_api_base_url") or kwargs.get("api_base_url")
        if isinstance(base, str) and base:
            self.api_base_url = base

        # Optional directory override for auth.json
        dir_override = kwargs.get("openai_codex_path")
        if isinstance(dir_override, str) and dir_override:
            self._oauth_dir_override = Path(dir_override)

        # 1) File exists + readable + parseable
        ok, errors = self._validate_credentials_file_exists()
        if not ok:
            self._fail_init(errors)
            return

        # 2) Load credentials into memory
        if not await self._load_auth():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        # 3) Structure validation
        if self._auth_credentials is not None:
            ok, errors = self._validate_credentials_structure(self._auth_credentials)
            if not ok:
                self._fail_init(errors)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        # 4) Start file watching and mark functional
        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()
        logger.info(f"Credentials file validation passed for {self.name}.")

        # Optionally prefetch models (non-fatal if it fails)
        import contextlib

        with contextlib.suppress(Exception):
            await self.list_models()

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        **kwargs: Any,
    ):
        # Runtime validation with throttling
        ok, errors = self._validate_runtime_credentials()
        if not ok:
            self._degrade(errors)
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_codex_credentials_invalid",
                    "message": f"OpenAI Codex credentials validation failed: {'; '.join(errors)}",
                    "details": {
                        "backend": self.name,
                        "validation_errors": errors,
                        "suggestion": "Please check your OAuth credentials file and ensure it contains valid tokens.access_token or OPENAI_API_KEY",
                    },
                },
            )

        # Verify credentials are loaded (should happen in initialize())
        # Do not call _load_auth() here - it's unprotected and creates race conditions
        if not self.api_key:
            self._degrade(["OAuth credentials not initialized"])
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_codex_credentials_unavailable",
                    "message": "OpenAI Codex credentials not initialized. Backend may have failed to start.",
                    "details": {
                        "backend": self.name,
                        "validation_errors": self.get_validation_errors(),
                        "suggestion": "Check backend initialization logs. Ensure auth.json exists and contains valid tokens.",
                    },
                },
            )

        if self._is_codex_model(effective_model):
            try:
                result = await self._call_codex_responses_api(
                    request_data=request_data,
                    processed_messages=processed_messages,
                    effective_model=effective_model,
                    domain_request=request_data,
                )
                if not self.is_functional:
                    self._recover()
                return result
            except Exception as e:
                if (
                    isinstance(e, AuthenticationError | HTTPException)
                    and hasattr(e, "status_code")
                    and e.status_code in (401, 403)
                ):
                    self._degrade([f"Authentication failed: {e!s}"])
                raise

        # Delegate to parent with our token
        try:
            result = await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                **kwargs,
            )
            # If we reach here, a call was successful - mark as recovered if we were degraded
            if not self.is_functional:
                self._recover()
            return result
        except Exception as e:
            # Check if it's an auth-related error and degrade accordingly
            if (
                isinstance(e, AuthenticationError | HTTPException)
                and hasattr(e, "status_code")
                and e.status_code in (401, 403)
            ):
                self._degrade([f"Authentication failed: {e!s}"])
            raise

    def __del__(self) -> None:
        """Cleanup file watcher on destruction."""
        self._stop_file_watching()


backend_registry.register_backend("openai-codex", OpenAICodexConnector)
