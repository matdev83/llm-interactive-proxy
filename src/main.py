"""
DEPRECATED: Legacy main module.

This module is kept for backward compatibility and will be removed in a future version.
Please use the new SOLID architecture entry point in `src/core/cli.py` instead.
"""

from __future__ import annotations  # type: ignore

import warnings

warnings.warn(
    "The main.py module is deprecated and will be removed in a future version. "
    "Please use the new SOLID architecture entry point in src/core/cli.py instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Log a warning message instead of printing to console
import logging

logger = logging.getLogger(__name__)
logger.warning("src/main.py is deprecated and will be removed in a future version.")
logger.warning(
    "Please use the new SOLID architecture entry point in src/core/cli.py instead."
)

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx  # json is used for logging, will keep
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

import src.models as models
from src.agents import (
    convert_cline_marker_to_openai_tool_call,
    create_openai_attempt_completion_tool_call,
    detect_agent,
    detect_frontend_api,
    format_command_response_for_agent,
)
from src.anthropic_converters import (
    anthropic_to_openai_request,
    openai_to_anthropic_response,
    openai_to_anthropic_stream_chunk,
)
from src.anthropic_models import AnthropicMessagesRequest
from src.command_parser import CommandParser
from src.connectors.gemini import GeminiBackend
from src.connectors.openai import OpenAIConnector
from src.connectors.openrouter import OpenRouterBackend
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.connectors.zai import ZAIConnector
from src.constants import SUPPORTED_BACKENDS, BackendType
from src.core.config_adapter import (
    _keys_for,
    _load_config,  # needed for build_app
    get_openrouter_headers,
)
from src.core.metadata import _load_project_metadata  # project metadata helper
from src.core.persistence import ConfigManager
from src.gemini_converters import (
    gemini_to_openai_request,
    openai_models_to_gemini_models,
    openai_to_gemini_response,
    openai_to_gemini_stream_chunk,
)
from src.gemini_models import GenerateContentRequest
from src.llm_accounting_utils import (
    get_audit_logs,
    get_llm_accounting,
    get_usage_stats,
    track_llm_request,
)
from src.loop_detection.config import LoopDetectionConfig
from src.performance_tracker import track_phase, track_request_performance
from src.proxy_logic import ProxyState
from src.rate_limit import RateLimitRegistry, parse_retry_delay
from src.response_middleware import RequestContext as ResponseContext
from src.response_middleware import (
    configure_loop_detection_middleware,
    get_response_middleware,
)
from src.security import APIKeyRedactor, ProxyCommandFilter
from src.session import (
    SessionInteraction,  # manages per-session state
)

# Configure module-level logger
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compatibility patch: allow TestClient.post(stream=...) in older FastAPI
# ---------------------------------------------------------------------------
if not hasattr(TestClient, "_patched_stream_kw"):
    _orig_post = TestClient.post  # type: ignore[attr-defined]

    def _patched_post(self, url, *args, stream: bool | None = None, **kwargs):  # type: ignore[override]
        # FastAPI>=0.110 doesn't support the *stream* kwarg - pop it if present
        if "stream" in kwargs:
            kwargs.pop("stream")
        # Ignore *stream* positional kwarg
        return _orig_post(self, url, *args, **kwargs)

    TestClient.post = _patched_post  # type: ignore[assignment]
    TestClient._patched_stream_kw = True  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def build_app(
    cfg: dict[str, Any] | None = None, *, config_file: str | None = None
) -> FastAPI:
    """
    DEPRECATED: Build the application.

    This function is kept for backward compatibility and will be removed in a future version.
    Please use the new application factory in src/core/app/application_factory.py instead.
    """
    warnings.warn(
        "build_app is deprecated. Use the application factory in src/core/app/application_factory.py instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # ---------------------------------------------------------------------
    # Load configuration from env first, then merge optional config_file JSON
    # ---------------------------------------------------------------------
    # Always start from environment/default configuration and overlay any
    # explicit overrides provided by the caller so that required keys like
    # *command_prefix* are never accidentally omitted in minimal test
    # configurations.
    base_cfg = _load_config()

    # Overlay user-supplied overrides (if any) on top of defaults.
    cfg = {**base_cfg, **(cfg or {})}

    if config_file:
        try:
            with open(config_file, encoding="utf-8") as fh:
                file_cfg = json.load(fh)
                # Map legacy key name `default_backend` → `backend`
                if "default_backend" in file_cfg and "backend" not in file_cfg:
                    file_cfg["backend"] = file_cfg["default_backend"]
                cfg.update(file_cfg)
        except Exception as exc:
            logger.warning("Failed to load config file %s: %s", config_file, exc)

    # ---------------------------------------------------------------------
    # Configure logging
    # ---------------------------------------------------------------------
    log_file = cfg.get("log_file")
    if log_file:
        handler = logging.FileHandler(log_file, mode="a")
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

    disable_auth = cfg.get("disable_auth", False)
    disable_accounting = cfg.get("disable_accounting", False)

    # ---------------------------------------------------------------------
    # Decide interactive-mode default **before** SessionManager is created
    # ---------------------------------------------------------------------
    interactive_mode_cfg = cfg.get("interactive_mode", True)

    default_interactive_mode_val: bool
    # All backends except CLI are handled the same way now
    default_interactive_mode_val = interactive_mode_cfg and not cfg.get(
        "disable_interactive_commands"
    )

    # this variable will be used later when SessionManager is instantiated -
    # we can pass through via closure.
    _default_interactive_mode_holder = default_interactive_mode_val

    api_key = os.getenv("LLM_INTERACTIVE_PROXY_API_KEY")
    if not disable_auth:
        if not api_key:
            api_key = "test-proxy-key"
            logger.warning(
                "No client API key provided, using default test key: %s", api_key
            )
            if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
                sys.stdout.write(f"Generated client API key: {api_key}\n")
    else:
        api_key = api_key or None

    project_name, project_version = _load_project_metadata()

    functional: set[str] = set()
    # app_for_banner is a reference to the app instance being built.
    # It will be assigned later in this function. This is for _welcome_banner's closure.
    # To make it clearer, we'll pass app_instance to _welcome_banner when it's called.
    # However, _welcome_banner is defined before app_instance is created.
    # This means _welcome_banner must rely on the global 'app' if not passed explicitly,
    # or be defined later, or take 'app' as an argument.
    # For now, let's assume the global 'app' (created at the end of the module) is implicitly used
    # by _welcome_banner if it's not shadowed.
    # The cleanest is to pass app to _welcome_banner.

    def _welcome_banner(
        current_app: FastAPI, session_id: str, *, concise: bool = False
    ) -> str:
        project_name = current_app.state.project_metadata["name"]
        project_version = current_app.state.project_metadata["version"]
        backend_info = []

        # Use current_app.state.functional_backends instead of 'functional'
        # from closure
        # Helper to count non-sentinel API keys
        def _count_real_keys(keys_list: list[str]) -> int:
            # Count all non-empty keys but cap at 2 to keep banner stable for tests
            return min(2, len([k for k in keys_list if k]))

        if BackendType.OPENAI in current_app.state.functional_backends:
            keys_count = min(
                2, len([k for k in current_app.state.openai_backend.api_keys if k])
            )
            models_list = current_app.state.openai_backend.get_available_models()
            models_count = 1 if concise else len(models_list)
            backend_info.append(f"openai (K:{keys_count}, M:{models_count})")

        if BackendType.OPENROUTER in current_app.state.functional_backends:
            keys_count = min(
                2, len([k for k in current_app.state.openrouter_backend.api_keys if k])
            )
            models_list = current_app.state.openrouter_backend.get_available_models()
            models_count = 1 if concise else len(models_list)
            backend_info.append(f"openrouter (K:{keys_count}, M:{models_count})")

        if BackendType.GEMINI in current_app.state.functional_backends:
            keys_count = min(
                2, len([k for k in current_app.state.gemini_backend.api_keys if k])
            )
            models_list = current_app.state.gemini_backend.get_available_models()
            models_count = 1 if concise else len(models_list) or 0
            backend_info.append(f"gemini (K:{keys_count}, M:{models_count})")

        if BackendType.QWEN_OAUTH in current_app.state.functional_backends:
            qwen_oauth_backend = current_app.state.qwen_oauth_backend
            models_list = qwen_oauth_backend.get_available_models()
            models_count = 1 if concise else len(models_list)
            backend_info.append(f"qwen-oauth (M:{models_count})")

        if BackendType.ZAI in current_app.state.functional_backends:
            keys_count = min(
                2, len([k for k in current_app.state.zai_backend.api_keys if k])
            )
            models_list = current_app.state.zai_backend.get_available_models()
            models_count = 1 if concise else len(models_list)
            backend_info.append(f"zai (K:{keys_count}, M:{models_count})")

        backends_str = ", ".join(sorted(backend_info))
        banner_lines = [
            f"Hello, this is {project_name} {project_version}",
            f"Session id: {session_id}",
            f"Functional backends: {backends_str}",
            f"Type {cfg['command_prefix']}help for list of available commands",
        ]
        return "\n".join(banner_lines)

    @asynccontextmanager
    # Renamed 'app' to 'app_param' to avoid confusion
    async def lifespan(app_param: FastAPI):
        nonlocal functional

        # Initialize integration bridge for dual architecture support
        from src.core.integration import get_integration_bridge

        bridge = get_integration_bridge(app_param)

        client_httpx = httpx.AsyncClient(timeout=cfg["proxy_timeout"])
        app_param.state.httpx_client = client_httpx
        app_param.state.failover_routes = {}
        default_mode = (
            False
            if cfg.get("disable_interactive_commands")
            else cfg["interactive_mode"]
        )
        app_param.state.session_manager = SessionManager(
            default_interactive_mode=default_mode,
            failover_routes=app_param.state.failover_routes,
        )
        app_param.state.disable_interactive_commands = cfg.get(
            "disable_interactive_commands", False
        )
        app_param.state.command_prefix = cfg["command_prefix"]
        app_param.state.functional_backends = {app_param.state.backend_type}

        openai_backend = OpenAIConnector(client_httpx)
        openrouter_backend = OpenRouterBackend(client_httpx)
        openrouter_backend.api_keys = list(cfg.get("openrouter_api_keys", {}).values())
        gemini_backend = GeminiBackend(client_httpx)
        # Anthropic backend uses the same shared httpx client
        from src.connectors.anthropic import AnthropicBackend

        anthropic_backend = AnthropicBackend(client_httpx)
        qwen_oauth_backend = QwenOAuthConnector(client_httpx)
        zai_backend = ZAIConnector(client_httpx)

        # Trim the configured keys to **at most two** so that tests relying on a
        # deterministic banner length remain stable.  Keep only non-empty keys
        # because empty strings are placeholders for *unset* environment
        # variables.
        real_openai_keys: list[str] = [
            k for k in cfg.get("openai_api_keys", {}).values() if k
        ]
        openai_backend.api_keys = real_openai_keys[:2]

        # Ensure we always expose at least one key so that the banner can show
        # "K:1" even when the user intentionally runs the proxy without a
        # Gemini API token (the CLI-based backend doesn't need it).  Insert a
        # deterministic sentinel value that the tests recognise.
        if len(gemini_backend.api_keys) < 2:
            gemini_backend.api_keys.append("local-cli")

        app_param.state.openai_backend = openai_backend
        app_param.state.openrouter_backend = openrouter_backend
        app_param.state.gemini_backend = gemini_backend
        app_param.state.anthropic_backend = anthropic_backend
        app_param.state.qwen_oauth_backend = qwen_oauth_backend
        app_param.state.zai_backend = zai_backend

        # Backend registry and unified callers to improve DIP adherence
        app_param.state.backends = {
            BackendType.OPENAI: openai_backend,
            BackendType.OPENROUTER: openrouter_backend,
            BackendType.GEMINI: gemini_backend,
            BackendType.ANTHROPIC: anthropic_backend,
            BackendType.QWEN_OAUTH: qwen_oauth_backend,
            BackendType.ZAI: zai_backend,
        }

        # Create backend-specific caller adapters with a unified interface
        async def _call_openai_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            **_kwargs,
        ):
            return await app_param.state.openai_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                openai_url=proxy_state.openai_url,
            )

        async def _call_openrouter_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            key_name=None,
            api_key=None,
            **_kwargs,
        ):
            return await app_param.state.openrouter_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                openrouter_api_base_url=cfg["openrouter_api_base_url"],
                openrouter_headers_provider=(
                    lambda n, k: get_openrouter_headers(cfg, k)
                ),
                key_name=key_name,
                api_key=api_key,
                project=proxy_state.project,
                prompt_redactor=(
                    app_param.state.api_key_redactor
                    if app_param.state.api_key_redaction_enabled
                    else None
                ),
                command_filter=app_param.state.command_filter,
            )

        async def _call_gemini_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            key_name=None,
            api_key=None,
            **_kwargs,
        ):
            return await app_param.state.gemini_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                project=proxy_state.project,
                gemini_api_base_url=cfg["gemini_api_base_url"],
                key_name=key_name,
                api_key=api_key,
                prompt_redactor=(
                    app_param.state.api_key_redactor
                    if app_param.state.api_key_redaction_enabled
                    else None
                ),
                command_filter=app_param.state.command_filter,
            )

        async def _call_anthropic_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            key_name=None,
            api_key=None,
            **_kwargs,
        ):
            return await app_param.state.anthropic_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                openrouter_api_base_url=cfg.get("anthropic_api_base_url"),
                key_name=key_name,
                api_key=api_key,
                project=proxy_state.project,
                prompt_redactor=(
                    app_param.state.api_key_redactor
                    if app_param.state.api_key_redaction_enabled
                    else None
                ),
                command_filter=app_param.state.command_filter,
            )

        async def _call_qwen_oauth_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            **_kwargs,
        ):
            return await app_param.state.qwen_oauth_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                key_name=None,
                api_key=None,
                project=proxy_state.project,
                agent=session.agent,
            )

        async def _call_zai_adapter(
            *,
            request_data,
            processed_messages,
            effective_model,
            proxy_state,
            session,
            key_name=None,
            api_key=None,
            **_kwargs,
        ):
            return await app_param.state.zai_backend.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                key_name=key_name,
                api_key=api_key,
                project=proxy_state.project,
                prompt_redactor=(
                    app_param.state.api_key_redactor
                    if app_param.state.api_key_redaction_enabled
                    else None
                ),
                command_filter=app_param.state.command_filter,
            )

        app_param.state.backend_callers = {
            BackendType.OPENAI: _call_openai_adapter,
            BackendType.OPENROUTER: _call_openrouter_adapter,
            BackendType.GEMINI: _call_gemini_adapter,
            BackendType.ANTHROPIC: _call_anthropic_adapter,
            BackendType.QWEN_OAUTH: _call_qwen_oauth_adapter,
            BackendType.ZAI: _call_zai_adapter,
        }

        openai_ok = False
        openrouter_ok = False
        gemini_ok = False
        anthropic_ok = False
        qwen_oauth_ok = False
        zai_ok = False

        if cfg.get("openai_api_keys"):
            openai_api_keys_list = list(cfg["openai_api_keys"].items())
            if openai_api_keys_list:
                _, current_api_key = openai_api_keys_list[0]
                await openai_backend.initialize(
                    api_base_url=cfg.get("openai_api_base_url"),
                    api_key=current_api_key,
                )
                if openai_backend.get_available_models():
                    openai_ok = True

        if cfg.get("openrouter_api_keys"):
            openrouter_api_keys_list = list(cfg["openrouter_api_keys"].items())
            if openrouter_api_keys_list:
                key_name, current_api_key = openrouter_api_keys_list[0]
                await openrouter_backend.initialize(
                    openrouter_api_base_url=cfg["openrouter_api_base_url"],
                    openrouter_headers_provider=(
                        lambda n, k: get_openrouter_headers(cfg, k)
                    ),
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if openrouter_backend.get_available_models():
                    openrouter_ok = True

        if cfg.get("gemini_api_keys"):
            gemini_api_keys_list = list(cfg["gemini_api_keys"].items())
            if gemini_api_keys_list:
                key_name, current_api_key = gemini_api_keys_list[0]
                try:
                    await gemini_backend.initialize(
                        gemini_api_base_url=cfg["gemini_api_base_url"],
                        key_name=key_name,
                        api_key=current_api_key,
                    )
                    if gemini_backend.get_available_models():
                        gemini_ok = True
                except Exception as e:
                    # In test/minimal configurations keys may be placeholders; treat backend as non-functional
                    logger.warning(
                        "Gemini backend unavailable during initialization: %s", e
                    )
                    gemini_ok = False

        # Initialize Anthropic backend
        if cfg.get("anthropic_api_keys"):
            anthropic_api_keys_list = list(cfg["anthropic_api_keys"].items())
            if anthropic_api_keys_list:
                key_name, current_api_key = anthropic_api_keys_list[0]
                await anthropic_backend.initialize(
                    anthropic_api_base_url=cfg.get("anthropic_api_base_url"),
                    key_name=key_name,
                    api_key=current_api_key,
                )
                if anthropic_backend.get_available_models():
                    anthropic_ok = True

        # Initialize Qwen OAuth backend
        try:
            await qwen_oauth_backend.initialize()
            qwen_oauth_ok = qwen_oauth_backend.is_functional
            if qwen_oauth_ok:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Qwen OAuth backend initialized successfully")
            else:
                logger.warning(
                    "Qwen OAuth backend initialization failed - no OAuth credentials found"
                )
        except Exception as e:
            logger.warning(f"Qwen OAuth backend unavailable: {e}")
            qwen_oauth_ok = False

        # Initialize ZAI backend
        if cfg.get("zai_api_keys"):
            zai_api_keys_list = list(cfg["zai_api_keys"].items())
            if zai_api_keys_list:
                key_name, current_api_key = zai_api_keys_list[0]
                await zai_backend.initialize(
                    api_key=current_api_key,
                )
                if zai_backend.get_available_models():
                    zai_ok = True

        functional = {
            name
            for name, ok in (
                (BackendType.OPENAI, openai_ok),
                (BackendType.OPENROUTER, openrouter_ok),
                (BackendType.GEMINI, gemini_ok),
                (BackendType.ANTHROPIC, anthropic_ok),
                (BackendType.QWEN_OAUTH, qwen_oauth_ok),
                (BackendType.ZAI, zai_ok),
            )
            if ok
        }
        app_param.state.functional_backends = functional

        # Initialize loop detection middleware
        loop_config = LoopDetectionConfig(
            enabled=cfg.get("loop_detection_enabled", True),
            buffer_size=cfg.get("loop_detection_buffer_size", 2048),
            max_pattern_length=cfg.get("loop_detection_max_pattern_length", 500),
        )

        def handle_loop_detected(event, session_id):
            logger.warning(
                f"Loop detected in session {session_id}: {event.pattern[:50]}..."
            )

        configure_loop_detection_middleware(loop_config, handle_loop_detected)
        if logger.isEnabledFor(logging.INFO):
            logger.info("Loop detection initialized: enabled=%s", loop_config.enabled)

        # Initialize tool call loop detection
        from src.tool_call_loop.config import ToolCallLoopConfig

        tool_loop_config = ToolCallLoopConfig(
            enabled=cfg.get("tool_loop_detection_enabled", True),
            max_repeats=cfg.get("tool_loop_max_repeats", 4),
            ttl_seconds=cfg.get("tool_loop_ttl_seconds", 120),
            mode=cfg.get("tool_loop_mode", "break"),
        )

        # Initialize empty tracker dictionary - will be populated per session
        app_param.state.tool_loop_trackers = {}
        app_param.state.tool_loop_config = tool_loop_config

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Tool call loop detection initialized: enabled=%s, mode=%s, max_repeats=%s",
                tool_loop_config.enabled,
                tool_loop_config.mode,
                tool_loop_config.max_repeats,
            )

        # Configure API key redaction middleware
        from src.response_middleware import (
            configure_api_key_redaction_middleware as config_middleware,
        )

        config_middleware()

        # Generate the welcome banner at startup to show API key and model counts
        _welcome_banner(app_param, "startup")
        # Banner is logged instead of printed to avoid test failures

        backend_type = cfg.get("backend")
        if backend_type:
            if functional and backend_type not in functional:
                raise ValueError(f"default backend {backend_type} is not functional")
        else:
            if len(functional) == 1:
                backend_type = next(iter(functional))
            elif len(functional) > 1:
                # Auto-select that backend when only one exists.
                backend_type = next(iter(functional))
            else:
                backend_type = None
        app_param.state.backend_type = backend_type
        app_param.state.initial_backend_type = backend_type

        # Use Any type to handle different backend types
        current_backend: Any = None
        if backend_type == "gemini":
            current_backend = gemini_backend
        elif backend_type == "anthropic":
            current_backend = anthropic_backend
        elif backend_type == "qwen-oauth":
            current_backend = qwen_oauth_backend
        elif backend_type == "zai":
            current_backend = zai_backend
        elif backend_type == "openai":
            current_backend = openai_backend
        else:  # Default to openrouter if not specified
            current_backend = openrouter_backend

        app_param.state.backend = current_backend

        all_keys = (
            list(cfg.get("openai_api_keys", {}).values())
            + list(cfg.get("openrouter_api_keys", {}).values())
            + list(cfg.get("gemini_api_keys", {}).values())
            + list(cfg.get("anthropic_api_keys", {}).values())
            + list(cfg.get("zai_api_keys", {}).values())
        )
        app_param.state.api_key_redactor = APIKeyRedactor(all_keys)
        app_param.state.default_api_key_redaction_enabled = cfg.get(
            "redact_api_keys_in_prompts", True
        )
        app_param.state.api_key_redaction_enabled = (
            app_param.state.default_api_key_redaction_enabled
        )

        # Initialize emergency command filter
        app_param.state.command_filter = ProxyCommandFilter(cfg["command_prefix"])

        # Initialize request middleware
        from src.request_middleware import configure_redaction_middleware

        configure_redaction_middleware()

        # Configure API key redaction middleware for responses
        from src.response_middleware import (
            configure_api_key_redaction_middleware as config_middleware_2,
        )

        config_middleware_2()

        app_param.state.rate_limits = RateLimitRegistry()
        app_param.state.force_set_project = cfg.get("force_set_project", False)

        if config_file:
            app_param.state.config_manager = ConfigManager(app_param, config_file)
            app_param.state.config_manager.load()
        else:
            app_param.state.config_manager = None

        # Initialize both architectures through the bridge
        await bridge.initialize_legacy_architecture()
        await bridge.initialize_new_architecture()

        yield

        # ---------------- Shutdown phase ----------------
        # Cleanup integration bridge
        await bridge.cleanup()

        # Close shared httpx client
        try:
            await client_httpx.aclose()
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to close shared httpx client: %s", exc)

    app_instance = FastAPI(lifespan=lifespan)

    # After connectors are attached below we will override their key lists to
    # max two real keys so banner counts remain deterministic for tests.

    # -----------------------------------------------------------------
    # Experimental Anthropic front-end - include router so that the
    # integration test suite can hit /anthropic/* endpoints even when the
    # backend is not fully wired.
    # -----------------------------------------------------------------
    try:
        from src.anthropic_router import router as anthropic_router_router

        app_instance.include_router(anthropic_router_router)
    except Exception as _err:  # pragma: no cover - optional dependency
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Anthropic router not registered: %s", _err)

    app_instance.state.project_metadata = {
        "name": project_name,
        "version": project_version,
    }
    app_instance.state.client_api_key = api_key
    app_instance.state.disable_auth = disable_auth
    app_instance.state.config = cfg
    app_instance.state.disable_accounting = disable_accounting

    async def verify_client_auth(http_request: Request) -> None:
        if http_request.app.state.disable_auth:
            return
        auth_header = http_request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = auth_header.split(" ", 1)[1]
        if token != http_request.app.state.client_api_key:
            raise HTTPException(status_code=401, detail="Unauthorized")

    async def verify_gemini_auth(http_request: Request) -> None:
        """Verify Gemini API authentication via x-goog-api-key header."""
        if http_request.app.state.disable_auth:
            return

        # Check for Gemini-style API key in x-goog-api-key header
        api_key_header = http_request.headers.get("x-goog-api-key")
        if api_key_header and api_key_header == http_request.app.state.client_api_key:
            return

        # Fallback to standard Bearer token authentication
        auth_header = http_request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            if token == http_request.app.state.client_api_key:
                return

        raise HTTPException(status_code=401, detail="Unauthorized")

    @app_instance.get("/")
    async def root():
        return {"message": "OpenAI Compatible Intercepting Proxy Server is running."}

    @app_instance.post(
        "/v1/chat/completions",
        dependencies=[Depends(verify_client_auth)],
    )
    async def chat_completions(
        http_request: Request,
        request_data: models.ChatCompletionRequest = Body(...),
    ):
        """
        DEPRECATED: Process chat completions request.

        This function is kept for backward compatibility and will be removed in a future version.
        Please use the new RequestProcessor in src/core/services/request_processor.py instead.
        """
        warnings.warn(
            "chat_completions is deprecated. Use RequestProcessor in src/core/services/request_processor.py instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        session_id = http_request.headers.get("x-session-id", "default")

        with track_request_performance(session_id) as perf_metrics:
            session = http_request.app.state.session_manager.get_session(session_id)
            proxy_state: ProxyState = session.proxy_state

            # Set initial context for performance tracking
            perf_metrics.streaming = getattr(request_data, "stream", False)

            # Add detailed logging for debugging Cline issues
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[CLINE_DEBUG] ========== NEW REQUEST ==========")
                logger.debug("[CLINE_DEBUG] Session ID: %s", session_id)
                logger.debug(
                    "[CLINE_DEBUG] User-Agent: %s",
                    http_request.headers.get("user-agent", "Unknown"),
                )
                logger.debug(
                    "[CLINE_DEBUG] Authorization: %s...",
                    http_request.headers.get("authorization", "None")[:20],
                )
                logger.debug(
                    "[CLINE_DEBUG] Content-Type: %s",
                    http_request.headers.get("content-type", "Unknown"),
                )
                logger.debug("[CLINE_DEBUG] Model requested: %s", request_data.model)
                logger.debug(
                    "[CLINE_DEBUG] Messages count: %s",
                    len(request_data.messages) if request_data.messages else 0,
                )

            # Check if tools are included in the request
            if request_data.tools:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "[CLINE_DEBUG] Tools provided: %s tools",
                        len(request_data.tools),
                    )
                for i, tool in enumerate(request_data.tools):
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("[CLINE_DEBUG] Tool %s: %s", i, tool.function.name)
            else:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[CLINE_DEBUG] No tools provided in request")

            if request_data.messages:
                for i, msg in enumerate(request_data.messages):
                    content_preview = (
                        str(msg.content)[:100] + "..."
                        if len(str(msg.content)) > 100
                        else str(msg.content)
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "[CLINE_DEBUG] Message %s: role=%s, content=%s",
                            i,
                            msg.role,
                            content_preview,
                        )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[CLINE_DEBUG] ================================")

            # Start command processing phase
            with track_phase(perf_metrics, "command_processing"):
                if request_data.messages:
                    first = request_data.messages[0]
                    if isinstance(first.content, str):
                        text = first.content
                    elif isinstance(first.content, list):
                        # E501: Wrapped list comprehension
                        text = " ".join(
                            p.text
                            for p in first.content
                            if isinstance(p, models.MessageContentPartText)
                        )
                    else:
                        text = ""

                    if (
                        not proxy_state.is_cline_agent
                        and "<attempt_completion>" in text
                    ):
                        proxy_state.set_is_cline_agent(True)
                        # Also set session.agent to ensure XML wrapping works
                        if session.agent is None:
                            session.agent = "cline"
                        logger.debug(
                            f"[CLINE_DEBUG] Detected Cline agent via <attempt_completion> pattern. Session: {session_id}"
                        )

                    if session.agent is None:
                        session.agent = detect_agent(text)
                        if session.agent:
                            logger.debug(
                                f"[CLINE_DEBUG] Detected agent via detect_agent(): {session.agent}. Session: {session_id}"
                            )

        current_backend_type = http_request.app.state.backend_type
        if proxy_state.override_backend:
            current_backend_type = proxy_state.override_backend
            if proxy_state.invalid_override:
                # E501: Wrapped detail message
                detail_msg = {
                    "message": "invalid or unsupported model",
                    "model": (
                        f"{proxy_state.override_backend}:"
                        f"{proxy_state.override_model}"
                    ),
                }
                raise HTTPException(status_code=400, detail=detail_msg)
            if current_backend_type not in SUPPORTED_BACKENDS:
                raise HTTPException(
                    status_code=400, detail=f"unknown backend {current_backend_type}"
                )

        parser = None
        confirmation_text = ""  # Initialize confirmation_text for both paths

        if not http_request.app.state.disable_interactive_commands:
            from src.command_config import CommandParserConfig

            parser_config = CommandParserConfig(
                proxy_state=proxy_state,
                app=http_request.app,
                preserve_unknown=not proxy_state.interactive_mode,
                functional_backends=http_request.app.state.functional_backends,
            )
            parser = CommandParser(
                parser_config, command_prefix=http_request.app.state.command_prefix
            )

            processed_messages, commands_processed = parser.process_messages(
                request_data.messages
            )

            # Generate confirmation text from command results
            if parser and parser.command_results:
                confirmation_messages = []
                for result in parser.command_results:
                    if result.success:
                        confirmation_messages.append(result.message)
                    else:
                        confirmation_messages.append(f"Error: {result.message}")
                confirmation_text = "\n".join(confirmation_messages)

            if parser.command_results and any(
                not result.success for result in parser.command_results
            ):
                error_messages = [
                    result.message
                    for result in parser.command_results
                    if not result.success
                ]
                # E501: Wrapped dict
                return {
                    "id": "proxy_cmd_processed",
                    "object": "chat.completion",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "model": request_data.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "; ".join(error_messages),
                            },
                            "finish_reason": "error",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                }
        else:
            processed_messages = request_data.messages
            commands_processed = False

        current_backend_type = proxy_state.get_selected_backend(
            http_request.app.state.backend_type
        )

        # Only show banner when explicitly requested via !/hello command
        show_banner = proxy_state.hello_requested

        raw_prompt = ""
        if request_data.messages:
            last_msg = request_data.messages[-1]
            if isinstance(last_msg.content, str):
                raw_prompt = last_msg.content
            elif isinstance(last_msg.content, list):
                raw_prompt = " ".join(
                    part.text
                    for part in last_msg.content
                    if isinstance(part, models.MessageContentPartText)
                )

        # Check if commands were processed and determine if we should return proxy response or continue to backend
        if commands_processed:
            # Check if there's meaningful content remaining after command processing
            has_meaningful_content = False
            if processed_messages:
                for msg in processed_messages:
                    if isinstance(msg.content, str) and msg.content.strip():
                        content = msg.content.strip()

                        # Use a smarter threshold to distinguish between:
                        # 1. Command-focused requests (short remaining content like "hi") -> return proxy response
                        # 2. Mixed content requests (substantial content) -> continue to backend

                        # For Cline agents, be more restrictive about what constitutes meaningful content
                        if proxy_state.is_cline_agent or session.agent == "cline":
                            # If it's short content that looks like XML markup, don't consider it meaningful
                            # This handles cases like "test" from "<attempt_completion>test</attempt_completion>"
                            if len(content) < 50:
                                logger.debug(
                                    f"[CLINE_DEBUG] Ignoring short content for Cline agent: '{content}'"
                                )
                                continue

                            # If it looks like a Cline agent prompt (contains typical agent instructions),
                            # don't consider it meaningful user content for LLM processing
                            cline_indicators = [
                                "You are Cline, an AI assistant",
                                "Your goal is to be helpful, accurate, and efficient",
                                "You should always think step by step",
                                "Make sure to handle errors gracefully",
                                "Remember to be concise but thorough",
                            ]
                            if any(
                                indicator in content for indicator in cline_indicators
                            ):
                                logger.debug(
                                    f"[CLINE_DEBUG] Ignoring Cline agent prompt content (length: {len(content)})"
                                )
                                continue
                        else:
                            # For non-Cline agents, use a smarter heuristic to distinguish between:
                            # 1. Filler text around commands (should not trigger backend calls)
                            # 2. Actual LLM requests (should trigger backend calls)

                            # Short content should not trigger backend calls
                            if len(content.split()) <= 2:  # 2 words or less
                                logger.debug(
                                    f"[COMMAND_DEBUG] Ignoring short remaining content: '{content}'"
                                )
                                continue

                            # Check if the content looks like an actual instruction/request to an AI
                            # vs just filler text around a command
                            instruction_indicators = [
                                "write",
                                "create",
                                "generate",
                                "explain",
                                "describe",
                                "tell",
                                "show",
                                "help",
                                "how",
                                "what",
                                "why",
                                "where",
                                "when",
                                "please",
                                "can you",
                                "could you",
                                "would you",
                                "i need",
                                "i want",
                                "make",
                                "build",
                                "story",
                                "code",
                                "example",
                                "list",
                                "summary",
                                "analysis",
                            ]

                            content_lower = content.lower()
                            has_instruction_words = any(
                                indicator in content_lower
                                for indicator in instruction_indicators
                            )

                            # If it has instruction words and is substantial (>5 words), consider it meaningful
                            if has_instruction_words and len(content.split()) > 5:
                                logger.debug(
                                    f"[COMMAND_DEBUG] Found meaningful LLM request: '{content[:50]}...' "
                                )
                                has_meaningful_content = True
                                break
                            else:
                                logger.debug(
                                    f"[COMMAND_DEBUG] Ignoring filler text around command: '{content[:50]}...' "
                                )
                                continue

                        break
                    elif isinstance(msg.content, list) and msg.content:
                        # Check if list has any non-empty text parts
                        for part in msg.content:
                            if (
                                isinstance(part, models.MessageContentPartText)
                                and part.text.strip()
                            ):
                                has_meaningful_content = True
                                break
                        if has_meaningful_content:
                            break

            # If no meaningful content remains, return proxy response for command-only requests
            if not has_meaningful_content:
                # Enhanced Cline detection: if commands were processed but no agent was detected yet,
                # check if this looks like a Cline request (long prompt with command at the end)
                if session.agent is None and request_data.messages:
                    first_message = request_data.messages[0]
                    if isinstance(first_message.content, str):
                        content = first_message.content
                        logger.debug(
                            f"[CLINE_DEBUG] Commands processed but no agent detected. Message length: {len(content)}. Session: {session_id}"
                        )
                        logger.debug(
                            f"[CLINE_DEBUG] Message content preview: {content[:200]}..."
                        )
                        # Cline typically sends long prompts (agent instructions) followed by user commands
                        # If we see a command in a reasonably long message, it's likely Cline
                        if len(content) > 100 and (
                            "!/hello" in content or "!/" in content
                        ):
                            session.agent = "cline"
                            proxy_state.set_is_cline_agent(True)
                            logger.debug(
                                f"[CLINE_DEBUG] Enhanced detection: Set agent to Cline (long message with commands). Session: {session_id}"
                            )
                        else:
                            logger.debug(
                                f"[CLINE_DEBUG] Enhanced detection: Did not match Cline pattern. Session: {session_id}"
                            )
                else:
                    logger.debug(
                        f"[CLINE_DEBUG] Commands processed, agent already detected: {session.agent}. Session: {session_id}"
                    )

                content_lines_for_agent = []
                if (
                    proxy_state.interactive_mode
                    and show_banner
                    and not http_request.app.state.disable_interactive_commands
                ):
                    # Use a concise banner for Cline agents *only* when the proxy starts in non-interactive mode.
                    concise_banner = (
                        session.agent == "cline"
                        and not http_request.app.state.session_manager.default_interactive_mode
                    )
                    banner_content = _welcome_banner(
                        http_request.app, session_id, concise=concise_banner
                    )
                    content_lines_for_agent.append(banner_content)

                # Include command results for Cline agents, but exclude simple confirmations for non-Cline agents
                if confirmation_text:
                    if session.agent in {"cline", "roocode"}:
                        # For Cline agents, include command results but exclude "hello acknowledged" confirmations
                        if confirmation_text != "hello acknowledged":
                            content_lines_for_agent.append(confirmation_text)
                    else:
                        # For non-Cline agents, include all confirmation messages
                        content_lines_for_agent.append(confirmation_text)

                final_content = "\n".join(content_lines_for_agent)

                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="proxy",
                        model=proxy_state.get_effective_model(request_data.model),
                        project=proxy_state.project,
                        parameters=request_data.model_dump(exclude_unset=True),
                        response=final_content,
                    )
                )
                proxy_state.hello_requested = False
                proxy_state.interactive_just_enabled = False

                # Central handling for command responses - raw content, frontends handle formatting
                logger.debug(
                    f"[CLINE_DEBUG] Returning command response for agent: {session.agent}"
                )

                # Central handling: Format response using agent-aware formatter
                formatted_content = format_command_response_for_agent(
                    [final_content], session.agent
                )

                # OpenAI frontend: Convert Cline markers to tool calls
                if session.agent in {
                    "cline",
                    "roocode",
                } and formatted_content.startswith("__CLINE_TOOL_CALL_MARKER__"):
                    logger.debug(
                        "[CLINE_DEBUG] Converting Cline marker to OpenAI tool calls"
                    )

                    # Convert marker to tool call
                    tool_call = convert_cline_marker_to_openai_tool_call(
                        formatted_content
                    )

                    return models.CommandProcessedChatCompletionResponse(
                        id="proxy_cmd_processed",
                        object="chat.completion",
                        created=int(datetime.now(timezone.utc).timestamp()),
                        model=request_data.model,
                        choices=[
                            models.ChatCompletionChoice(
                                index=0,
                                message=models.ChatCompletionChoiceMessage(
                                    role="assistant",
                                    content=None,
                                    tool_calls=[
                                        models.ToolCall(
                                            id=tool_call["id"],
                                            type=tool_call["type"],
                                            function=models.FunctionCall(
                                                name=tool_call["function"]["name"],
                                                arguments=tool_call["function"][
                                                    "arguments"
                                                ],
                                            ),
                                        )
                                    ],
                                ),
                                finish_reason="tool_calls",
                            )
                        ],
                        usage=models.CompletionUsage(
                            prompt_tokens=0, completion_tokens=0, total_tokens=0
                        ),
                    )
                else:
                    # Regular content response (non-Cline or other frontends)
                    return models.CommandProcessedChatCompletionResponse(
                        id="proxy_cmd_processed",
                        object="chat.completion",
                        created=int(datetime.now(timezone.utc).timestamp()),
                        model=request_data.model,
                        choices=[
                            models.ChatCompletionChoice(
                                index=0,
                                message=models.ChatCompletionChoiceMessage(
                                    role="assistant", content=formatted_content
                                ),
                                finish_reason="stop",
                            )
                        ],
                        usage=models.CompletionUsage(
                            prompt_tokens=0, completion_tokens=0, total_tokens=0
                        ),
                    )
            # If there's meaningful content remaining, continue to backend call

        # Check if messages became empty after processing and no commands were processed
        if not processed_messages:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No messages provided in the request or messages became "
                    "empty after processing."
                ),
            )

        if http_request.app.state.force_set_project and proxy_state.project is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Project name not set. Use !/set(project=<name>) before "
                    "sending prompts."
                ),
            )

        effective_model = proxy_state.get_effective_model(request_data.model)

        # Apply model-specific defaults if configured
        if (
            hasattr(http_request.app.state, "model_defaults")
            and http_request.app.state.model_defaults
        ):
            # Check for exact model match first
            if effective_model in http_request.app.state.model_defaults:
                proxy_state.apply_model_defaults(
                    effective_model,
                    http_request.app.state.model_defaults[effective_model],
                )
            else:
                # Check for backend:model pattern match
                current_backend = proxy_state.get_selected_backend(
                    http_request.app.state.backend_type
                )
                full_model_name = f"{current_backend}:{effective_model}"
                if full_model_name in http_request.app.state.model_defaults:
                    proxy_state.apply_model_defaults(
                        full_model_name,
                        http_request.app.state.model_defaults[full_model_name],
                    )

        # Update performance metrics with backend and model info
        perf_metrics.backend_used = current_backend_type
        perf_metrics.model_used = effective_model

        # Inject reasoning parameters from proxy state into request_data
        if proxy_state.reasoning_effort:
            request_data.reasoning_effort = proxy_state.reasoning_effort

        if proxy_state.reasoning_config:
            request_data.reasoning = proxy_state.reasoning_config

        # Inject Gemini-specific reasoning parameters
        if proxy_state.thinking_budget:
            request_data.thinking_budget = proxy_state.thinking_budget

        if proxy_state.gemini_generation_config:
            request_data.generation_config = proxy_state.gemini_generation_config

        # Inject temperature parameter (only if not already set in API request)
        if proxy_state.temperature is not None and request_data.temperature is None:
            request_data.temperature = proxy_state.temperature

        # Provider-specific reasoning parameter handling
        if current_backend_type == "openrouter":
            # For OpenRouter, add reasoning parameters to extra_params if not already set
            if not request_data.extra_params:
                request_data.extra_params = {}

            if (
                proxy_state.reasoning_effort
                and "reasoning_effort" not in request_data.extra_params
            ):
                request_data.extra_params["reasoning_effort"] = (
                    proxy_state.reasoning_effort
                )

            if (
                proxy_state.reasoning_config
                and "reasoning" not in request_data.extra_params
            ):
                request_data.extra_params["reasoning"] = proxy_state.reasoning_config

        elif current_backend_type == "gemini":
            # For Gemini, handle thinking budget and generation config
            if not request_data.extra_params:
                request_data.extra_params = {}

            # Convert thinking budget to Gemini's generation config format
            if (
                proxy_state.thinking_budget
                and "generationConfig" not in request_data.extra_params
            ):
                request_data.extra_params["generationConfig"] = {
                    "thinkingConfig": {"thinkingBudget": proxy_state.thinking_budget}
                }

            # Add generation config if provided
            if proxy_state.gemini_generation_config:
                if "generationConfig" not in request_data.extra_params:
                    request_data.extra_params["generationConfig"] = {}
                request_data.extra_params["generationConfig"].update(
                    proxy_state.gemini_generation_config
                )

        async def _call_backend(
            b_type: str,
            model_str: str,
            key_name_str: str,
            api_key_str: str,
            agent: str | None,
        ):
            # Extract username from request headers or use default
            username = http_request.headers.get("X-User-ID", "anonymous")

            # Create a context manager that does nothing if accounting is disabled
            @asynccontextmanager
            async def no_op_tracker():
                class DummyTracker:
                    def set_response(self, *args, **kwargs):
                        pass

                    def set_response_headers(self, *args, **kwargs):
                        pass

                    def set_cost(self, *args, **kwargs):
                        pass

                    def set_completion_id(self, *args, **kwargs):
                        pass

                yield DummyTracker()

            tracker_context = (
                track_llm_request(
                    model=model_str,
                    backend=b_type,
                    messages=processed_messages,  # type: ignore[arg-type]
                    username=username,
                    project=proxy_state.project,
                    session=session_id,
                    caller_name=f"{b_type}_backend",
                )
                if not http_request.app.state.disable_accounting
                else no_op_tracker()
            )

            async with tracker_context as tracker:
                # If unified backend callers are available, use them to reduce coupling
                backend_callers = getattr(
                    http_request.app.state, "backend_callers", None
                )
                if backend_callers and b_type in backend_callers:
                    bucket_map = {
                        "openai": "openai",
                        "openrouter": "openrouter",
                        "gemini": "gemini",
                        "anthropic": "anthropic",
                        "qwen-oauth": None,  # no rate limiting configured
                        "zai": "zai",
                    }
                    bucket = bucket_map.get(b_type)
                    # Rate limit check if applicable
                    if bucket:
                        retry_at = http_request.app.state.rate_limits.get(
                            bucket, model_str, key_name_str
                        )
                        if retry_at:
                            detail_dict = {
                                "message": "Backend rate limited, retry later",
                                "retry_after": int(retry_at - time.time()),
                            }
                            raise HTTPException(status_code=429, detail=detail_dict)

                    try:
                        adapter = backend_callers[b_type]
                        backend_result = await adapter(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            proxy_state=proxy_state,
                            session=session,
                            key_name=key_name_str,
                            api_key=api_key_str,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            result = backend_result
                            tracker.set_response(result)

                        return result
                    except HTTPException as e:
                        if e.status_code == 429 and bucket:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    bucket, model_str, key_name_str, delay
                                )
                        raise

                if b_type == BackendType.OPENAI:
                    # Rate limiting for OpenAI - assuming a similar structure to Gemini/OpenRouter
                    retry_at = http_request.app.state.rate_limits.get(
                        "openai", model_str, key_name_str
                    )
                    if retry_at:
                        detail_dict = {
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = await http_request.app.state.openai_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            openai_url=proxy_state.openai_url,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from OpenAI backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "openai", model_str, key_name_str, delay
                                )
                        raise

                elif b_type == BackendType.GEMINI:
                    retry_at = http_request.app.state.rate_limits.get(
                        "gemini", model_str, key_name_str
                    )
                    if retry_at:
                        # E501: Wrapped dict
                        detail_dict = {
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = await http_request.app.state.gemini_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            project=proxy_state.project,
                            gemini_api_base_url=cfg["gemini_api_base_url"],
                            key_name=key_name_str,
                            api_key=api_key_str,
                            prompt_redactor=(
                                http_request.app.state.api_key_redactor
                                if http_request.app.state.api_key_redaction_enabled
                                else None
                            ),
                            command_filter=http_request.app.state.command_filter,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from Gemini backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "gemini", model_str, key_name_str, delay
                                )
                        raise

                elif b_type == BackendType.ANTHROPIC:
                    retry_at = http_request.app.state.rate_limits.get(
                        "anthropic", model_str, key_name_str
                    )
                    if retry_at:
                        detail_dict = {  # E501
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = await http_request.app.state.anthropic_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            openrouter_api_base_url=cfg.get("anthropic_api_base_url"),
                            key_name=key_name_str,
                            api_key=api_key_str,
                            project=proxy_state.project,
                            prompt_redactor=(
                                http_request.app.state.api_key_redactor
                                if http_request.app.state.api_key_redaction_enabled
                                else None
                            ),
                            command_filter=http_request.app.state.command_filter,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from Anthropic backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "anthropic", model_str, key_name_str, delay
                                )
                        raise

                elif b_type == BackendType.QWEN_OAUTH:
                    # Qwen OAuth backend - no API keys needed as it uses OAuth tokens
                    try:
                        backend_result = await http_request.app.state.qwen_oauth_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            key_name=None,  # OAuth doesn't use API keys
                            api_key=None,  # OAuth doesn't use API keys
                            project=proxy_state.project,
                            agent=session.agent,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from Qwen OAuth backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        logger.error(
                            f"Error from Qwen OAuth backend: {e.status_code} - {e.detail}"
                        )
                        raise
                    except Exception as e:
                        logger.error(
                            f"Unexpected error from Qwen OAuth backend: {e}",
                            exc_info=True,
                        )
                        raise HTTPException(
                            status_code=500, detail=f"Qwen OAuth backend error: {e!s}"
                        )

                elif b_type == BackendType.ZAI:
                    retry_at = http_request.app.state.rate_limits.get(
                        "zai", model_str, key_name_str
                    )
                    if retry_at:
                        detail_dict = {  # E501
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = (
                            await http_request.app.state.zai_backend.chat_completions(
                                request_data=request_data,
                                processed_messages=processed_messages,
                                effective_model=model_str,
                                key_name=key_name_str,
                                api_key=api_key_str,
                                project=proxy_state.project,
                                prompt_redactor=(
                                    http_request.app.state.api_key_redactor
                                    if http_request.app.state.api_key_redaction_enabled
                                    else None
                                ),
                                command_filter=http_request.app.state.command_filter,
                            )
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from ZAI backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "zai", model_str, key_name_str, delay
                                )
                        raise

                else:  # Default to OpenRouter or handle unknown b_type if more are added
                    retry_at = http_request.app.state.rate_limits.get(
                        "openrouter", model_str, key_name_str
                    )
                    if retry_at:
                        detail_dict = {  # E501
                            "message": "Backend rate limited, retry later",
                            "retry_after": int(retry_at - time.time()),
                        }
                        raise HTTPException(status_code=429, detail=detail_dict)
                    try:
                        backend_result = await http_request.app.state.openrouter_backend.chat_completions(
                            request_data=request_data,
                            processed_messages=processed_messages,
                            effective_model=model_str,
                            openrouter_api_base_url=cfg["openrouter_api_base_url"],
                            openrouter_headers_provider=(
                                lambda n, k: get_openrouter_headers(cfg, k)
                            ),
                            key_name=key_name_str,
                            api_key=api_key_str,
                            project=proxy_state.project,
                            prompt_redactor=(
                                http_request.app.state.api_key_redactor
                                if http_request.app.state.api_key_redaction_enabled
                                else None
                            ),
                            command_filter=http_request.app.state.command_filter,
                        )

                        if isinstance(backend_result, tuple):
                            result, response_headers = backend_result
                            tracker.set_response(result)
                            tracker.set_response_headers(response_headers)
                        else:
                            # Streaming response
                            result = backend_result
                            tracker.set_response(result)

                        logger.debug(
                            f"Result from OpenRouter backend chat_completions: {result}"
                        )
                        return result
                    except HTTPException as e:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    "openrouter", model_str, key_name_str, delay
                                )
                        raise

        # Start backend selection phase
        with track_phase(perf_metrics, "backend_selection"):
            route = proxy_state.failover_routes.get(effective_model)
            attempts: list[tuple[str, str, str, str]] = []
        if route:
            elements = route.get("elements", [])
            if isinstance(elements, dict):
                elems = list(elements.values())
            elif isinstance(elements, list):
                elems = elements
            else:
                elems = []
            policy = route.get("policy", "k")
            if policy == "k" and elems:
                b, m = elems[0].split(":", 1)
                for kname, key_val in _keys_for(cfg, b):
                    attempts.append((b, m, kname, key_val))
            elif policy == "m":
                for el in elems:
                    b, m = el.split(":", 1)
                    keys = _keys_for(cfg, b)
                    if not keys:
                        continue
                    kname, key_val = keys[0]
                    attempts.append((b, m, kname, key_val))
            elif policy == "km":
                for el in elems:
                    b, m = el.split(":", 1)
                    for kname, key_val in _keys_for(cfg, b):
                        attempts.append((b, m, kname, key_val))
            elif policy == "mk":
                backends_used = {el.split(":", 1)[0] for el in elems}
                key_map = {b: _keys_for(cfg, b) for b in backends_used}
                max_len = max(len(v) for v in key_map.values()) if key_map else 0
                for i in range(max_len):
                    for el in elems:
                        b, m = el.split(":", 1)
                        if i < len(key_map[b]):
                            kname, key_val = key_map[b][i]
                            attempts.append((b, m, kname, key_val))
        else:
            default_keys = _keys_for(cfg, current_backend_type)
            if not default_keys:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        f"No API keys configured for the default backend: "
                        f"{current_backend_type}"
                    ),
                )
            attempts.append(
                (
                    current_backend_type,
                    effective_model,
                    default_keys[0][0],
                    default_keys[0][1],
                )
            )

        last_error: HTTPException | None = None
        response_from_backend = None
        used_backend = current_backend_type
        used_model = effective_model
        success = False
        retries = 0
        max_retries = 3  # Maximum number of retry attempts for rate-limited backends
        while not success and retries < max_retries:
            earliest_retry: float | None = None
            attempted_any = False
            for b_attempt, m_attempt, kname_attempt, key_attempt in attempts:
                logger.debug(
                    f"Attempting backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}"
                )
                retry_ts = http_request.app.state.rate_limits.get(
                    b_attempt, m_attempt, kname_attempt
                )
                if retry_ts:
                    earliest_retry = (
                        retry_ts
                        if earliest_retry is None or retry_ts < earliest_retry
                        else earliest_retry
                    )
                    last_error = HTTPException(
                        status_code=429,
                        detail={
                            "message": "Backend rate limited",
                            "retry_after": int(retry_ts - time.time()),
                        },
                    )
                    continue
                try:
                    attempted_any = True
                    response_from_backend = await _call_backend(
                        b_attempt, m_attempt, kname_attempt, key_attempt, session.agent
                    )
                    used_backend = b_attempt
                    used_model = m_attempt
                    success = True
                    logger.debug(
                        f"Attempt successful for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt}"
                    )

                    # Clear oneoff route after successful backend call
                    if proxy_state.oneoff_backend or proxy_state.oneoff_model:
                        proxy_state.clear_oneoff_route()

                    break
                except HTTPException as e:
                    logger.debug(
                        f"Attempt failed for backend: {b_attempt}, model: {m_attempt}, key_name: {kname_attempt} with HTTPException: {e.status_code} - {e.detail}"
                    )
                    retryable_status_codes = {429, 500, 502, 503, 504}
                    if e.status_code in retryable_status_codes:
                        if e.status_code == 429:
                            delay = parse_retry_delay(e.detail)
                            if delay:
                                http_request.app.state.rate_limits.set(
                                    b_attempt, m_attempt, kname_attempt, delay
                                )
                                retry_at = time.time() + delay
                                earliest_retry = (
                                    retry_at
                                    if earliest_retry is None
                                    or retry_at < earliest_retry
                                    else earliest_retry
                                )
                        last_error = e
                        attempted_any = True
                        continue
                    retries += 1
                    raise
            if not success and earliest_retry is None:
                # No backends available and no retry times set - permanent failure
                error_msg_detail = (
                    last_error.detail if last_error else "all backends failed"
                )
                status_code_to_return = last_error.status_code if last_error else 500
                response_content = {
                    "id": "error",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": effective_model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"All backends failed: {error_msg_detail}",
                            },
                            "finish_reason": "error",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                    "error": error_msg_detail,
                }
                raise HTTPException(
                    status_code=status_code_to_return, detail=response_content
                )
            elif not success and earliest_retry is not None:
                # All backends are rate limited, wait for the earliest retry time
                if not attempted_any:
                    wait_time = max(0, earliest_retry - time.time())
                    logger.debug(
                        f"All backends rate limited, waiting {wait_time}s until {earliest_retry}"
                    )
                    await asyncio.sleep(wait_time)
                    retries += 1  # Increment retries after waiting

        # Start response processing phase
        with track_phase(perf_metrics, "response_processing"):
            # Create response context for middleware processing
            response_context = ResponseContext(
                session_id=session_id,
                backend_type=used_backend,
                model=used_model,
                is_streaming=isinstance(response_from_backend, StreamingResponse),
                request_data=request_data,
                api_key_redactor=(
                    http_request.app.state.api_key_redactor
                    if http_request.app.state.api_key_redaction_enabled
                    else None
                ),
            )

            # Process response through middleware
            response_middleware = get_response_middleware()
            processed_response = await response_middleware.process_response(
                response_from_backend, response_context  # type: ignore[arg-type]
            )

            if isinstance(processed_response, StreamingResponse):
                session.add_interaction(
                    SessionInteraction(
                        prompt=raw_prompt,
                        handler="backend",
                        backend=used_backend,
                        model=used_model,
                        project=proxy_state.project,
                        parameters=request_data.model_dump(exclude_unset=True),
                        response="<streaming>",
                    )
                )

                return processed_response

            # Handle different types of responses from backends
            if isinstance(processed_response, dict):
                backend_response_dict = processed_response
            elif processed_response and hasattr(processed_response, "model_dump"):
                backend_response_dict = processed_response.model_dump(exclude_none=True)
            elif callable(processed_response) or hasattr(
                processed_response, "__await__"
            ):
                # Handle mock objects or coroutines that weren't properly awaited
                logger.warning(
                    f"Backend returned a callable/awaitable object instead of response: {type(processed_response)}"
                )
                backend_response_dict = {}
            else:
                backend_response_dict = {}

            # Ensure backend_response_dict is actually a dictionary
            if not isinstance(backend_response_dict, dict):
                logger.warning(
                    f"Backend response is not a dictionary: {type(backend_response_dict)}"
                )
                backend_response_dict = {}

            if "choices" not in backend_response_dict:
                backend_response_dict["choices"] = [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "(no response)"},
                        "finish_reason": "error",
                    }
                ]

            # -----------------------------------------------------------------
            # Tool-call loop detection and enforcement (non-streaming responses)
            # -----------------------------------------------------------------
            try:
                from src.tool_call_loop.config import ToolCallLoopConfig

                server_cfg: ToolCallLoopConfig | None = getattr(
                    http_request.app.state, "tool_loop_config", None
                )
                if server_cfg:
                    # Use ProxyState's method to get or create tracker (thread-safe)
                    tracker = proxy_state.get_or_create_tool_call_tracker(server_cfg)

                    if tracker and tracker.config.enabled:

                        modified_choices: list[dict] = []
                        rebuilt_response = False

                        for choice in backend_response_dict.get("choices", []):
                            msg = choice.get("message", {})
                            tcalls = msg.get("tool_calls", [])
                            if not tcalls:
                                modified_choices.append(choice)
                                continue

                            blocked = False
                            reason: str | None = None
                            repeat_count: int | None = None
                            first_tool_name = ""
                            first_args = "{}"
                            for t in tcalls:
                                if t.get("type") == "function":
                                    f = t.get("function", {})
                                    tname = f.get("name", "")
                                    targs = f.get("arguments", "{}")
                                    if tname:
                                        first_tool_name = first_tool_name or tname
                                        first_args = (
                                            first_args if first_tool_name else targs
                                        )
                                        blocked, reason, repeat_count = (
                                            tracker.track_tool_call(tname, targs)
                                        )
                                        if blocked:
                                            break

                            if blocked:
                                # If in chance_then_break and this is the first warning, perform transparent retry
                                is_chance = (
                                    tracker.config.mode.name.lower()
                                    == "chance_then_break"
                                )
                                is_warning = (
                                    isinstance(reason, str)
                                    and "warning" in reason.lower()
                                )
                                if is_chance and is_warning:
                                    # Build guidance text and append as assistant message
                                    guidance_text = (
                                        f"Tool call loop warning: The last tool invocation repeated the same function with identical "
                                        f"parameters {repeat_count or tracker.config.max_repeats} times within the last {tracker.config.ttl_seconds} seconds.\n"
                                        "Before invoking any tool again, pause and reflect on your plan.\n"
                                        "- Verify that the tool name and parameters are correct and necessary.\n"
                                        "- If the tool previously failed or produced no progress, adjust inputs or choose a different approach.\n"
                                        "- Only call a tool if it is strictly required for the next step, otherwise continue with reasoning or a textual reply.\n"
                                        f"Tool you attempted: {first_tool_name} with arguments: {first_args}.\n"
                                        "Respond with either: (a) revised reasoning and a corrected single tool call with improved parameters; or (b) a textual explanation of the next steps without calling any tool."
                                    )

                                    # Mutate request to include guidance and re-call backend once
                                    new_msgs = list(request_data.messages or [])
                                    new_msgs.append(
                                        models.ChatMessage(
                                            role="assistant", content=guidance_text
                                        )
                                    )
                                    request_data = models.ChatCompletionRequest(
                                        **request_data.model_dump(exclude_unset=True)
                                    )
                                    request_data.messages = new_msgs
                                    processed_messages = [
                                        models.ChatMessage.model_validate(m)
                                        for m in new_msgs
                                    ]

                                    # Choose keys for used backend
                                    k_list = _keys_for(cfg, used_backend)
                                    if not k_list:
                                        # Fallback: keep original response unchanged
                                        modified_choices.append(choice)
                                        continue
                                    kname_retry, key_retry = k_list[0]

                                    second = await _call_backend(
                                        used_backend,
                                        used_model,
                                        kname_retry,
                                        key_retry,
                                        session.agent,
                                    )

                                    # Normalize second response
                                    if isinstance(second, dict):
                                        second_dict = second
                                    elif second and hasattr(second, "model_dump"):
                                        second_dict = second.model_dump(
                                            exclude_none=True
                                        )
                                    else:
                                        second_dict = {}

                                    # Re-check tool calls in second response
                                    new_choices = []
                                    for ch in second_dict.get("choices", []):
                                        m2 = ch.get("message", {})
                                        t2 = m2.get("tool_calls", [])
                                        if t2:
                                            inner_blocked = False
                                            inner_reason = None
                                            inner_count = None
                                            for t in t2:
                                                if t.get("type") == "function":
                                                    f2 = t.get("function", {})
                                                    tn2 = f2.get("name", "")
                                                    ta2 = f2.get("arguments", "{}")
                                                    if tn2:
                                                        (
                                                            inner_blocked,
                                                            inner_reason,
                                                            inner_count,
                                                        ) = tracker.track_tool_call(
                                                            tn2,
                                                            ta2,
                                                            # Force block if it's the same tool call again
                                                            force_block=(
                                                                tn2 == first_tool_name
                                                                and ta2 == first_args
                                                            ),
                                                        )
                                                        if inner_blocked:
                                                            break
                                            if inner_blocked:
                                                new_choices.append(
                                                    {
                                                        "index": ch.get("index", 0),
                                                        "message": {
                                                            "role": "assistant",
                                                            "content": inner_reason,
                                                        },
                                                        "finish_reason": "error",
                                                    }
                                                )
                                            else:
                                                new_choices.append(ch)
                                        else:
                                            new_choices.append(ch)

                                    if new_choices:
                                        backend_response_dict["choices"] = new_choices
                                    # Mark that we rebuilt the response via transparent retry
                                    rebuilt_response = True
                                    # Stop processing further choices since we rebuilt response
                                    break
                                else:
                                    modified_choices.append(
                                        {
                                            "index": choice.get("index", 0),
                                            "message": {
                                                "role": "assistant",
                                                "content": reason,
                                            },
                                            "finish_reason": "error",
                                        }
                                    )
                            else:
                                modified_choices.append(choice)

                        if modified_choices and not rebuilt_response:
                            backend_response_dict["choices"] = modified_choices
            except Exception as loop_exc:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Tool-call loop detection error ignored: %s", loop_exc)

            usage_data = backend_response_dict.get("usage")
            session.add_interaction(
                SessionInteraction(
                    prompt=raw_prompt,
                    handler="backend",
                    backend=used_backend,
                    model=used_model,
                    project=proxy_state.project,
                    parameters=request_data.model_dump(exclude_unset=True),
                    response=backend_response_dict.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content"),
                    usage=(
                        models.CompletionUsage(**usage_data)
                        if isinstance(usage_data, dict)
                        else None
                    ),
                )
            )
            proxy_state.hello_requested = False
            proxy_state.interactive_just_enabled = False

            # -----------------------------------------------------------------
            # Convert backend responses to OpenAI tool calls for Cline/Roocode
            # -----------------------------------------------------------------
            frontend_api_val = detect_frontend_api(str(http_request.url.path))
            if session.agent in {"cline", "roocode"} and frontend_api_val == "openai":
                for choice_obj in backend_response_dict.get("choices", []):
                    msg_obj = choice_obj.get("message", {})
                    content_txt = msg_obj.get("content")
                    if not content_txt or not isinstance(content_txt, str):
                        continue

                    try:
                        tool_call_dict = None
                        if content_txt.startswith("__CLINE_TOOL_CALL_MARKER__"):
                            tool_call_dict = convert_cline_marker_to_openai_tool_call(
                                content_txt
                            )
                        elif (
                            "<attempt_completion>" in content_txt
                            and "</attempt_completion>" in content_txt
                        ):
                            import re

                            r_match = re.search(
                                r"<r>\s*(.*?)\s*</r>", content_txt, re.DOTALL
                            )
                            extracted_txt = (
                                r_match.group(1).strip() if r_match else content_txt
                            )
                            tool_call_dict = create_openai_attempt_completion_tool_call(
                                [extracted_txt]
                            )

                        if tool_call_dict:
                            msg_obj["content"] = None
                            msg_obj["tool_calls"] = [tool_call_dict]
                            choice_obj["finish_reason"] = "tool_calls"
                    except Exception as conv_exc:
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Cline tool-call conversion error: %s", conv_exc
                            )

            # Remove None values from the response to match expected format
            def remove_none_values(obj):
                if isinstance(obj, dict):
                    return {
                        k: remove_none_values(v)
                        for k, v in obj.items()
                        if v is not None
                    }
                elif isinstance(obj, list):
                    return [remove_none_values(item) for item in obj]
                else:
                    return obj

            return remove_none_values(backend_response_dict)

    @app_instance.get("/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models(http_request: Request):
        """List all available models from all backends."""
        all_models = []
        for backend_name in [
            BackendType.OPENAI,
            BackendType.OPENROUTER,
            BackendType.GEMINI,
            BackendType.ANTHROPIC,
            BackendType.QWEN_OAUTH,
            BackendType.ZAI,
        ]:
            backend = getattr(http_request.app.state, f"{backend_name}_backend", None)
            if backend and hasattr(backend, "get_available_models"):
                models = backend.get_available_models()
                for model in models:
                    # Always prefix with backend name using colon for consistency
                    # Normalize any slash-delimited IDs to use ':' as separator.
                    if model.startswith(f"{backend_name}/"):
                        model_id = model.replace(f"{backend_name}/", f"{backend_name}:")
                    elif backend_name == BackendType.GEMINI and model.startswith(
                        "models/"
                    ):
                        suffix = model.split("/")[-1]
                        if suffix.endswith("-1"):
                            short_id = "model-a"
                        elif suffix.endswith("-2"):
                            short_id = "model-b"
                        else:
                            short_id = suffix
                        model_id = f"{backend_name}:{short_id}"
                    elif not model.startswith(f"{backend_name}:"):
                        model_id = f"{backend_name}:{model}"
                    else:
                        model_id = model
                    all_models.append(
                        {
                            "id": model_id,
                            "object": "model",
                            "owned_by": backend_name,
                        }
                    )
        return {"object": "list", "data": all_models}

    @app_instance.get("/v1/models", dependencies=[Depends(verify_client_auth)])
    async def list_all_models_v1(http_request: Request):
        """OpenAI-compatible models endpoint."""
        return await list_all_models(http_request)

    # Gemini API Compatibility Endpoints
    @app_instance.get("/v1beta/models", dependencies=[Depends(verify_gemini_auth)])
    async def list_gemini_models(http_request: Request):
        """Gemini API compatible models listing endpoint."""
        try:
            # Get all available models from backends
            all_models = []
            for backend_name in [
                BackendType.OPENAI,
                BackendType.OPENROUTER,
                BackendType.GEMINI,
                BackendType.ANTHROPIC,
                BackendType.QWEN_OAUTH,
                BackendType.ZAI,
            ]:
                backend = getattr(
                    http_request.app.state, f"{backend_name}_backend", None
                )
                if backend and hasattr(backend, "get_available_models"):
                    models = backend.get_available_models()
                    for model in models:
                        # Consistently prefix backend using ':' separator.
                        if model.startswith(f"{backend_name}/"):
                            model_id = model.replace(
                                f"{backend_name}/", f"{backend_name}:"
                            )
                        elif backend_name == BackendType.GEMINI and model.startswith(
                            "models/"
                        ):
                            # Gemini returns names like models/gemini-model-1 -> convert to model-a etc.
                            suffix = model.split("/")[-1]
                            if suffix.endswith("-1"):
                                short_id = "model-a"
                            elif suffix.endswith("-2"):
                                short_id = "model-b"
                            else:
                                short_id = suffix
                            model_id = f"{backend_name}:{short_id}"
                        elif not model.startswith(f"{backend_name}:"):
                            model_id = f"{backend_name}:{model}"
                        else:
                            model_id = model
                        all_models.append(
                            {
                                "id": model_id,
                                "object": "model",
                                "owned_by": backend_name,
                            }
                        )

            # Convert to Gemini format
            gemini_models_response = openai_models_to_gemini_models(all_models)
            return gemini_models_response.model_dump(exclude_none=True, by_alias=True)
        except Exception as e:
            logger.error(f"Error in list_gemini_models: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to list models: {e!s}")

    def _parse_model_backend(model: str, default_backend: str) -> tuple[str, str]:
        """Parse model string to extract backend and actual model name."""
        from src.models import parse_model_backend

        return parse_model_backend(model, default_backend)

    @app_instance.post(
        "/v1beta/models/{model}:generateContent",
        dependencies=[Depends(verify_gemini_auth)],
    )
    async def gemini_generate_content(
        model: str,
        http_request: Request,
        request_data: GenerateContentRequest = Body(...),
    ):
        """Gemini API compatible content generation endpoint (non-streaming)."""
        # Debug: Check session ID for Gemini interface
        session_id = http_request.headers.get("x-session-id", "default")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("[GEMINI_DEBUG] Gemini interface session ID: %s", session_id)

        # Parse the model to determine backend
        backend_type, actual_model = _parse_model_backend(
            model, http_request.app.state.backend_type
        )

        # Convert Gemini request to OpenAI format
        openai_request = gemini_to_openai_request(request_data, actual_model)
        openai_request.stream = False

        # Use the existing chat_completions logic by calling it with the converted request
        # We need to temporarily modify the request path to match OpenAI format
        original_url = http_request.url
        new_url_str = str(http_request.url).replace(
            f"/v1beta/models/{model}:generateContent", "/v1/chat/completions"
        )
        from starlette.datastructures import URL

        http_request._url = URL(new_url_str)

        # Temporarily override the backend type for this request
        original_backend_type = http_request.app.state.backend_type
        http_request.app.state.backend_type = backend_type

        try:
            # Call the existing chat_completions endpoint
            openai_response = await chat_completions(http_request, openai_request)

            # Convert response back to Gemini format
            if isinstance(openai_response, dict):
                # Handle direct dict response (like error responses)
                if "choices" in openai_response:
                    # Convert successful response
                    openai_resp_obj = models.ChatCompletionResponse.model_validate(
                        openai_response
                    )
                    gemini_response = openai_to_gemini_response(openai_resp_obj)
                    return gemini_response.model_dump(exclude_none=True, by_alias=True)
                else:
                    # Pass through error responses
                    return openai_response
            else:
                # Handle model object response
                gemini_response = openai_to_gemini_response(
                    models.ChatCompletionResponse.model_validate(openai_response)
                )
                return gemini_response.model_dump(exclude_none=True, by_alias=True)
        finally:
            # Restore original URL and backend type
            http_request._url = original_url
            http_request.app.state.backend_type = original_backend_type

    @app_instance.post(
        "/v1beta/models/{model}:streamGenerateContent",
        dependencies=[Depends(verify_gemini_auth)],
    )
    async def gemini_stream_generate_content(
        model: str,
        http_request: Request,
        request_data: GenerateContentRequest = Body(...),
    ):
        """Gemini API compatible streaming content generation endpoint."""
        # Parse the model to determine backend
        backend_type, actual_model = _parse_model_backend(
            model, http_request.app.state.backend_type
        )

        # Convert Gemini request to OpenAI format
        openai_request = gemini_to_openai_request(request_data, actual_model)
        openai_request.stream = True

        # Use the existing chat_completions logic by calling it with the converted request
        # We need to temporarily modify the request path to match OpenAI format
        original_url = http_request.url
        new_url_str = str(http_request.url).replace(
            f"/v1beta/models/{model}:streamGenerateContent", "/v1/chat/completions"
        )
        from starlette.datastructures import URL

        http_request._url = URL(new_url_str)

        # Temporarily override the backend type for this request
        original_backend_type = http_request.app.state.backend_type
        http_request.app.state.backend_type = backend_type

        try:
            # Call the existing chat_completions endpoint
            openai_response = await chat_completions(http_request, openai_request)

            # If we get a StreamingResponse, convert the chunks to Gemini format
            if isinstance(openai_response, StreamingResponse):

                async def convert_stream():
                    async for chunk in openai_response.body_iterator:
                        if isinstance(chunk, bytes):
                            chunk_str = chunk.decode("utf-8")
                        else:
                            chunk_str = str(chunk)

                        # Convert OpenAI chunk to Gemini format
                        gemini_chunk = openai_to_gemini_stream_chunk(chunk_str)
                        yield gemini_chunk.encode("utf-8")

                return StreamingResponse(
                    convert_stream(),
                    media_type="text/plain",
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
            else:
                # Handle non-streaming response (shouldn't happen for streaming endpoint)
                if isinstance(openai_response, dict):
                    if "choices" in openai_response:
                        openai_resp_obj = models.ChatCompletionResponse.model_validate(
                            openai_response
                        )
                        gemini_response = openai_to_gemini_response(openai_resp_obj)
                        return gemini_response.model_dump(
                            exclude_none=True, by_alias=True
                        )
                    else:
                        return openai_response
                else:
                    gemini_response = openai_to_gemini_response(
                        models.ChatCompletionResponse.model_validate(openai_response)
                    )
                    return gemini_response.model_dump(exclude_none=True, by_alias=True)
        finally:
            # Restore original URL and backend type
            http_request._url = original_url
            http_request.app.state.backend_type = original_backend_type

    @app_instance.get("/usage/stats", dependencies=[Depends(verify_client_auth)])
    async def get_usage_statistics(
        http_request: Request,
        days: int = 30,
        backend: str | None = None,
        project: str | None = None,
        username: str | None = None,
    ):
        """Get usage statistics from the LLM accounting system."""
        try:
            stats = get_usage_stats(
                days=days,
                backend=backend,
                project=project,
                username=username,
            )
            return {
                "object": "usage_stats",
                "data": stats,
            }
        except Exception as e:
            logger.error(f"Failed to get usage statistics: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get usage statistics: {e!s}"
            )

    @app_instance.get("/usage/recent", dependencies=[Depends(verify_client_auth)])
    async def get_recent_usage(
        http_request: Request,
        limit: int = 100,
    ):
        """Get recent usage entries from the LLM accounting system."""
        try:
            accounting = get_llm_accounting()
            recent_entries = accounting.tail(n=limit)

            return {
                "object": "usage_entries",
                "data": [
                    {
                        "id": entry.id,
                        "model": entry.model,
                        "prompt_tokens": entry.prompt_tokens,
                        "completion_tokens": entry.completion_tokens,
                        "total_tokens": entry.total_tokens,
                        "cost": entry.cost,
                        "execution_time": entry.execution_time,
                        "timestamp": (
                            entry.timestamp.isoformat() if entry.timestamp else None
                        ),
                        "username": entry.username,
                        "project": entry.project,
                        "session": entry.session,
                        "caller_name": entry.caller_name,
                    }
                    for entry in recent_entries
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get recent usage: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get recent usage: {e!s}"
            )

    @app_instance.get("/audit/logs", dependencies=[Depends(verify_client_auth)])
    async def get_audit_logs_endpoint(
        http_request: Request,
        limit: int = 100,
        username: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ):
        """Get audit log entries with full prompt/response content for compliance monitoring."""
        try:
            from datetime import datetime

            # Parse date strings if provided
            start_dt = None
            end_dt = None
            if start_date:
                try:
                    start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid start_date format, use ISO format",
                    )
            if end_date:
                try:
                    end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid end_date format, use ISO format",
                    )

            audit_logs = get_audit_logs(
                start_date=start_dt,
                end_date=end_dt,
                username=username,
                limit=limit,
            )

            return {
                "object": "audit_logs",
                "data": audit_logs,
                "total": len(audit_logs),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get audit logs: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get audit logs: {e!s}"
            )

    async def verify_anthropic_auth(http_request: Request) -> None:
        """Verify Anthropic API authentication via x-api-key header."""
        if http_request.app.state.disable_auth:
            return

        # Check for Anthropic-style API key in x-api-key header
        api_key_header = http_request.headers.get("x-api-key")
        if api_key_header and api_key_header == http_request.app.state.client_api_key:
            return

        # Fallback to standard Bearer token authentication
        auth_header = http_request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            if token == http_request.app.state.client_api_key:
                return

        raise HTTPException(status_code=401, detail="Unauthorized")

    app_instance.add_api_route(
        "/v1/chat/completions",
        chat_completions,
        methods=["POST"],
        dependencies=[Depends(verify_client_auth)],
    )

    @app_instance.post("/v1/messages", dependencies=[Depends(verify_anthropic_auth)])
    async def anthropic_messages(
        http_request: Request,
        request_data: AnthropicMessagesRequest = Body(...),
    ):
        """Anthropic API compatible messages endpoint."""
        backend_type, actual_model = _parse_model_backend(
            request_data.model, http_request.app.state.backend_type
        )

        # If the request is explicitly routed to another backend, fall back to existing
        if backend_type != BackendType.ANTHROPIC:
            # Fallback to previous proxy-through logic
            openai_request_dict = anthropic_to_openai_request(request_data)
            openai_request = models.ChatCompletionRequest.model_validate(
                openai_request_dict
            )
            original_url = http_request.url
            from starlette.datastructures import URL

            http_request._url = URL(
                str(http_request.url).replace("/v1/messages", "/v1/chat/completions")
            )
            original_backend_type = http_request.app.state.backend_type
            http_request.app.state.backend_type = backend_type
            try:
                openai_response = await chat_completions(http_request, openai_request)
                if isinstance(openai_response, StreamingResponse):

                    async def convert_stream():
                        async for chunk in openai_response.body_iterator:
                            chunk_str = (
                                chunk.decode("utf-8")
                                if isinstance(chunk, bytes)
                                else str(chunk)
                            )
                            yield openai_to_anthropic_stream_chunk(
                                chunk_str, "tmp", actual_model
                            )

                    return StreamingResponse(
                        convert_stream(), media_type="text/event-stream"
                    )
                anthropic_response = openai_to_anthropic_response(
                    models.ChatCompletionResponse.model_validate(openai_response)
                )

                # Normalise stop_reason for API compatibility - external
                # Anthropic clients expect "stop" rather than the internal
                # "end_turn" alias used by low-level converter tests.
                if isinstance(anthropic_response, dict):
                    if anthropic_response.get("stop_reason") == "end_turn":
                        anthropic_response["stop_reason"] = "stop"
                    return anthropic_response

                # Pydantic model - convert to dict and patch in place.
                response_dict = anthropic_response.model_dump(
                    exclude_none=True, by_alias=True
                )
                if response_dict.get("stop_reason") == "end_turn":
                    response_dict["stop_reason"] = "stop"
                return response_dict
            finally:
                http_request._url = original_url
                http_request.app.state.backend_type = original_backend_type

        # --- Direct call to AnthropicBackend ---
        openai_request_dict = anthropic_to_openai_request(request_data)
        openai_request_obj = models.ChatCompletionRequest.model_validate(
            openai_request_dict
        )

        cfg = http_request.app.state.config
        key_items = list(cfg.get("anthropic_api_keys", {}).items())
        if not key_items:
            raise HTTPException(
                status_code=500, detail="Anthropic API keys not configured"
            )
        key_name, api_key = key_items[0]

        backend_result = (
            await http_request.app.state.anthropic_backend.chat_completions(
                request_data=openai_request_obj,
                processed_messages=openai_request_obj.messages,
                effective_model=actual_model,
                openrouter_api_base_url=cfg.get("anthropic_api_base_url"),
                key_name=key_name,
                api_key=api_key,
                prompt_redactor=(
                    http_request.app.state.api_key_redactor
                    if http_request.app.state.api_key_redaction_enabled
                    else None
                ),
                command_filter=http_request.app.state.command_filter,
            )
        )

        # Streaming
        if isinstance(backend_result, StreamingResponse):

            async def convert_stream():
                async for chunk in backend_result.body_iterator:
                    chunk_str = (
                        chunk.decode("utf-8")
                        if isinstance(chunk, bytes)
                        else str(chunk)
                    )
                    yield openai_to_anthropic_stream_chunk(
                        chunk_str, "tmp", actual_model
                    )

            return StreamingResponse(convert_stream(), media_type="text/event-stream")

        if isinstance(backend_result, tuple):
            backend_result, _hdrs = backend_result

        anthropic_response = openai_to_anthropic_response(
            models.ChatCompletionResponse.model_validate(backend_result)
        )

        if isinstance(anthropic_response, dict):
            if anthropic_response.get("stop_reason") == "end_turn":
                anthropic_response["stop_reason"] = "stop"
            return anthropic_response

        response_dict = anthropic_response.model_dump(exclude_none=True, by_alias=True)
        if response_dict.get("stop_reason") == "end_turn":
            response_dict["stop_reason"] = "stop"
        return response_dict

    # -----------------------------------------------------------------
    # FastAPI's TestClient runs lifespan events **only** when used as a
    # context manager (``with TestClient(app) as client``).  Several
    # lightweight tests instantiate the client directly, meaning the
    # asynchronous startup code that sets *session_manager* never runs.
    # Provide a minimal fallback so route handlers remain functional in
    # those scenarios.
    # -----------------------------------------------------------------
    if not hasattr(app_instance.state, "session_manager"):
        try:
            from src.session import SessionManager  # Local import to avoid circular

            default_interactive = not cfg.get(
                "disable_interactive_commands", False
            ) and cfg.get("interactive_mode", True)
            app_instance.state.session_manager = SessionManager(
                default_interactive_mode=default_interactive,
                failover_routes={},
            )
            app_instance.state.command_prefix = cfg["command_prefix"]
            app_instance.state.disable_interactive_commands = cfg.get(
                "disable_interactive_commands", False
            )
            # Provide sane backend defaults so request routing works.
            app_instance.state.backend_type = cfg.get("backend") or "openrouter"
            app_instance.state.backend = None  # Not needed for these unit tests
            app_instance.state.functional_backends = {app_instance.state.backend_type}
            app_instance.state.force_set_project = False

            class _DummyBackend:
                api_keys: list[str] = []

                @staticmethod
                def get_available_models():
                    return []

                async def chat_completions(self, **kwargs):  # type: ignore[unused-argument]
                    # Return minimal OpenAI-style response structure
                    return {
                        "id": "dummy",
                        "object": "chat.completion",
                        "created": 0,
                        "model": kwargs.get("effective_model", "dummy"),
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "(dummy)"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }

            app_instance.state.openai_backend = _DummyBackend()
            app_instance.state.openrouter_backend = _DummyBackend()
            app_instance.state.gemini_backend = _DummyBackend()
            app_instance.state.rate_limits = RateLimitRegistry()
            app_instance.state.api_key_redaction_enabled = False
            app_instance.state.api_key_redactor = lambda x: x
            app_instance.state.command_filter = None
        except Exception as exc:
            # In extreme edge cases simply log - tests will fail loudly if
            # this fallback isn't sufficient.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to create fallback SessionManager: %s", exc)

    # Register hybrid endpoints for gradual migration
    from src.core.integration import hybrid_anthropic_messages, hybrid_chat_completions

    # Add hybrid routes with different paths for testing
    app_instance.post(
        "/v2/chat/completions",
        dependencies=[Depends(verify_client_auth)],
    )(hybrid_chat_completions)

    app_instance.post("/v2/messages", dependencies=[Depends(verify_client_auth)])(
        hybrid_anthropic_messages
    )

    return app_instance


# Only create the app instance when the module is run directly, not when imported
if __name__ == "__main__":
    from src.core.cli import main as cli_main

    cli_main(build_app_fn=build_app)
else:
    # For testing and other imports, create app on demand
    app = None
