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
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
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
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.openai import OpenAIConnector
from src.connectors.openai_codex.compat import CompatibilityLayer
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.connectors.openai_codex.contracts import (
    CodexConnectorDependencies,
    CodexConnectorSettings,
    CodexPayload,
    CodexRequestContext,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolExecutionResult,
)
from src.connectors.openai_codex.credentials import (
    CredentialManager,
    OpenAICredentialsFileHandler,
)
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.payload import PayloadBuilder
from src.connectors.openai_codex.prompt import PromptResolver
from src.connectors.openai_codex.request_translator import RequestTranslator
from src.connectors.openai_codex.settings import SettingsLoader
from src.connectors.openai_codex.tool_schema import ToolSchemaResolver
from src.connectors.openai_codex.tool_schemas import get_codex_tool_schema
from src.connectors.openai_codex.tools import ToolExecutionService
from src.connectors.openai_codex.utils import build_codex_user_agent, message_to_text
from src.core.common.exceptions import AuthenticationError, ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.domain.model_utils import parse_model_with_params
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)
from src.core.domain.session_key import SessionKey
from src.core.domain.validation import ValidationResult
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_registry import backend_registry
from src.core.services.tool_text_renderer import OverrideRenderer
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

# Vendor prefix for OpenAI models in unified model naming convention
OPENAI_VENDOR_PREFIX = "openai"


class OpenAICodexConnector(OpenAIConnector):
    backend_type: str = "openai-codex"
    _DEBUG_OVERRIDE_DEFAULT = os.environ.get(
        "ENABLE_INTERNAL_BACKENDS_FOR_TESTS", "1"
    ).lower() not in {"0", "false", "no"}

    @property
    def has_static_credentials(self) -> bool:
        return False

    # Supported Codex models - exhaustive list
    SUPPORTED_CODEX_MODELS: tuple[str, ...] = (
        "gpt-5.1-codex-max",
        "gpt-5.1-codex",
        "gpt-5.1-codex-mini",
        "gpt-5.1",
    )
    # Pre-computed lowercased set for O(1) lookup
    _SUPPORTED_CODEX_MODELS_LOWER: frozenset[str] = frozenset(
        m.lower() for m in SUPPORTED_CODEX_MODELS
    )

    # Reasoning effort levels supported by Codex backend
    REASONING_EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh")
    DEFAULT_REASONING_EFFORT: str = "medium"
    # Only gpt-5.1-codex-max supports xhigh reasoning effort
    XHIGH_SUPPORTED_MODELS: tuple[str, ...] = ("gpt-5.1-codex-max",)
    # Pre-computed lowercased set for O(1) lookup
    _XHIGH_SUPPORTED_MODELS_LOWER: frozenset[str] = frozenset(
        m.lower() for m in XHIGH_SUPPORTED_MODELS
    )

    CODEX_PROMPT_RESOURCE_PACKAGE = "src.resources.codex"
    CODEX_PROMPT_RESOURCE_NAME = "gpt_5_codex_prompt.md"
    CODEX_ORIGINATOR = "codex_cli_rs"
    CODEX_VERSION_HEADER = "0.0.0"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
        dependencies: CodexConnectorDependencies | None = None,
    ) -> None:
        # Detect swapped positional args (backend factory passes translation_service)
        if translation_service is None and isinstance(
            response_processor, TranslationService
        ):
            translation_service = response_processor
            response_processor = None

        super().__init__(
            client=client,
            config=config,
            translation_service=translation_service,
            response_processor=response_processor,
        )
        self.disable_health_check()
        self.name = "openai-codex"
        self._enable_codex_backend_debugging_override = self._DEBUG_OVERRIDE_DEFAULT

        self._working_directory: str | None = None

        # Credentials and validation state
        self.is_functional = False
        self._credential_validation_errors: list[str] = []
        self._initialization_failed = False
        self._last_validation_time = 0.0

        # File watcher state
        self._file_observer_ref: BaseObserver | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._pending_reload_task: asyncio.Future[None] | None = None
        self._reload_scheduling_event = threading.Event()
        self._reload_task_lock = threading.Lock()
        self._shutdown_requested = threading.Event()

        # Dependency resolution
        self._dependencies = dependencies or self._resolve_dependencies()

        self._settings_loader = (
            self._dependencies.settings_loader
            if self._dependencies and self._dependencies.settings_loader is not None
            else SettingsLoader()
        )
        self._connector_settings_model = self._settings_loader.load(config)
        self._connector_settings = self._connector_settings_model.model_dump()

        self._default_capabilities = self._connector_settings_model.default_capabilities
        self._renderer_default = self._connector_settings["renderer"]["default"]
        self._renderer_fallback = self._connector_settings["renderer"]["fallback"]
        self._prompt_settings = self._connector_settings["prompt"]
        self._default_tool_schema_override = self._connector_settings["tool_schema"][
            "base_tools"
        ]
        self._custom_tool_schema_default = self._connector_settings["tool_schema"][
            "custom_tools"
        ]

        streaming_cfg = self._connector_settings.get("streaming", {})
        self._stream_retry_limit = int(streaming_cfg.get("max_retries", 2))
        backoff_seq = streaming_cfg.get("retry_backoff_seconds") or ()
        self._stream_retry_backoff = tuple(backoff_seq) if backoff_seq else ()

        self._capability_resolver = CodexCapabilityResolver(
            default_capabilities=self._default_capabilities,
            agent_overrides=self._connector_settings_model.agent_overrides,
        )

        # Credential manager
        self._credential_manager = (
            self._dependencies.credential_manager
            if self._dependencies and self._dependencies.credential_manager is not None
            else CredentialManager(self.client)
        )

        # Compatibility and tool execution
        compat_cfg = self._connector_settings["compatibility_layer"]
        self._compatibility_layer_enabled = bool(compat_cfg["enabled"])
        self._session_detector: SessionDetector | None = None
        if self._compatibility_layer_enabled:
            self._session_detector = SessionDetector(
                cache_ttl_seconds=compat_cfg["detection"]["cache_ttl_seconds"],
                heuristic_threshold=compat_cfg["detection"]["heuristic_threshold"],
            )

        self._kilo_tool_translator: KiloToolTranslator | None = None
        if self._compatibility_layer_enabled:
            self._kilo_tool_translator = KiloToolTranslator(self, None)

        self._tool_execution_service = (
            self._dependencies.tool_execution_service
            if self._dependencies
            and self._dependencies.tool_execution_service is not None
            else ToolExecutionService()
        )

        self._compatibility_layer = (
            self._dependencies.compatibility_layer
            if self._dependencies and self._dependencies.compatibility_layer is not None
            else CompatibilityLayer(
                session_detector=self._session_detector,
                kilo_translator=self._kilo_tool_translator,
                tool_execution_service=self._tool_execution_service,
            )
        )

        # Request/payload components
        self._request_translator = CodexRequestTranslator(self)
        self._request_translator_adapter = RequestTranslator(self._request_translator)
        self._prompt_resolver = PromptResolver()
        self._tool_schema_resolver = ToolSchemaResolver(
            settings=self._connector_settings_model,
            tool_execution_service=self._tool_execution_service,
        )

        self._payload_builder = (
            self._dependencies.payload_builder
            if self._dependencies and self._dependencies.payload_builder is not None
            else PayloadBuilder(
                connector=self,
                request_translator=self._request_translator_adapter,
                prompt_resolver=self._prompt_resolver,
                tool_schema_resolver=self._tool_schema_resolver,
                settings=self._connector_settings_model,
                message_to_text_converter=self._message_to_text,
            )
        )

        self._response_executor = (
            self._dependencies.response_executor
            if self._dependencies and self._dependencies.response_executor is not None
            else ResponseExecutor(
                base_connector=self,
                credential_manager=self._credential_manager,
                max_retries=self._stream_retry_limit,
                retry_backoff_seconds=self._stream_retry_backoff,
                compatibility_layer=self._compatibility_layer,
            )
        )

    def _resolve_dependencies(self) -> CodexConnectorDependencies | None:
        try:
            from src.core.di.services import get_or_build_service_provider

            provider = get_or_build_service_provider()
            return provider.get_service(CodexConnectorDependencies)
        except (ImportError, AttributeError, ServiceResolutionError) as err:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to resolve CodexConnectorDependencies: %s",
                    err,
                    exc_info=True,
                )
            return None

    def _refresh_settings_from_overrides(self) -> None:
        try:
            self._connector_settings_model = CodexConnectorSettings(
                **self._connector_settings
            )
        except (TypeError, ValidationError) as err:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to create CodexConnectorSettings from overrides, using loader: %s",
                    err,
                    exc_info=True,
                )
            self._connector_settings_model = self._settings_loader.load(self.config)
            self._connector_settings = self._connector_settings_model.model_dump()

        self._default_capabilities = self._connector_settings_model.default_capabilities
        self._renderer_default = self._connector_settings["renderer"]["default"]
        self._renderer_fallback = self._connector_settings["renderer"]["fallback"]
        self._prompt_settings = self._connector_settings["prompt"]
        self._default_tool_schema_override = self._connector_settings["tool_schema"][
            "base_tools"
        ]
        self._custom_tool_schema_default = self._connector_settings["tool_schema"][
            "custom_tools"
        ]

        streaming_cfg = self._connector_settings.get("streaming", {})
        self._stream_retry_limit = int(streaming_cfg.get("max_retries", 2))
        backoff_seq = streaming_cfg.get("retry_backoff_seconds") or ()
        self._stream_retry_backoff = tuple(backoff_seq) if backoff_seq else ()

        self._capability_resolver = CodexCapabilityResolver(
            default_capabilities=self._default_capabilities,
            agent_overrides=self._connector_settings_model.agent_overrides,
        )

        compat_cfg = self._connector_settings["compatibility_layer"]
        self._compatibility_layer_enabled = bool(compat_cfg["enabled"])
        if self._compatibility_layer_enabled and self._session_detector is None:
            self._session_detector = SessionDetector(
                cache_ttl_seconds=compat_cfg["detection"]["cache_ttl_seconds"],
                heuristic_threshold=compat_cfg["detection"]["heuristic_threshold"],
            )
        if not self._compatibility_layer_enabled:
            self._session_detector = None

        if hasattr(self._compatibility_layer, "_session_detector"):
            self._compatibility_layer._session_detector = self._session_detector

        if self._compatibility_layer_enabled and self._kilo_tool_translator is None:
            session_service = getattr(self, "_session_service", None)
            self._kilo_tool_translator = KiloToolTranslator(self, session_service)

        if hasattr(self._compatibility_layer, "_kilo_translator"):
            self._compatibility_layer._kilo_translator = self._kilo_tool_translator

        if isinstance(self._tool_schema_resolver, ToolSchemaResolver):
            self._tool_schema_resolver = ToolSchemaResolver(
                settings=self._connector_settings_model,
                tool_execution_service=self._tool_execution_service,
            )

        if isinstance(self._payload_builder, PayloadBuilder):
            self._payload_builder = PayloadBuilder(
                connector=self,
                request_translator=self._request_translator_adapter,
                prompt_resolver=self._prompt_resolver,
                tool_schema_resolver=self._tool_schema_resolver,
                settings=self._connector_settings_model,
                message_to_text_converter=self._message_to_text,
            )

        if isinstance(self._response_executor, ResponseExecutor):
            self._response_executor._max_retries = self._stream_retry_limit
            self._response_executor._retry_backoff_seconds = self._stream_retry_backoff

    @property
    def _auth_credentials(self) -> dict[str, Any] | None:
        return getattr(self._credential_manager, "_auth_credentials", None)

    @_auth_credentials.setter
    def _auth_credentials(self, value: dict[str, Any] | None) -> None:
        self._credential_manager._auth_credentials = value
        token = self._credential_manager.get_access_token()
        if token:
            self.api_key = token

    @property
    def _auth_path(self) -> Path | None:
        return getattr(self._credential_manager, "_auth_path", None)

    @_auth_path.setter
    def _auth_path(self, value: Path | None) -> None:
        self._credential_manager._auth_path = value

    @property
    def _oauth_dir_override(self) -> Path | None:
        return getattr(self._credential_manager, "_oauth_dir_override", None)

    @_oauth_dir_override.setter
    def _oauth_dir_override(self, value: Path | None) -> None:
        self._credential_manager._oauth_dir_override = value

    @property
    def _last_modified(self) -> float:
        return float(getattr(self._credential_manager, "_last_modified", 0.0))

    @_last_modified.setter
    def _last_modified(self, value: float) -> None:
        self._credential_manager._last_modified = float(value)

    @property
    def _file_observer(self) -> BaseObserver | None:
        return self._file_observer_ref

    @_file_observer.setter
    def _file_observer(self, value: BaseObserver | None) -> None:
        self._file_observer_ref = value

    @classmethod
    def _is_codex_model(cls, model_name: str) -> bool:
        """Return True when the model is a supported Codex model."""
        clean_model = strip_vendor_prefix(model_name.lower(), OPENAI_VENDOR_PREFIX)
        return clean_model in cls._SUPPORTED_CODEX_MODELS_LOWER

    @classmethod
    def _codex_system_prompt(cls) -> str:
        """Load the Codex system prompt from bundled resources or vendor sources."""
        return PromptResolver._codex_system_prompt()

    def _codex_user_agent(self) -> str:
        """Build a Codex CLI compatible User-Agent string."""
        return build_codex_user_agent(self.CODEX_ORIGINATOR, self.CODEX_VERSION_HEADER)

    def _codex_account_id(self) -> str | None:
        """Return the ChatGPT account_id from cached credentials when available."""
        if hasattr(self._credential_manager, "get_account_id"):
            account_id = self._credential_manager.get_account_id()
            return account_id if isinstance(account_id, str) else None
        return None

    @staticmethod
    def _message_to_text(message: Any) -> str:
        return message_to_text(message)

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

    def _extract_custom_instruction_sections(self, request_data: Any) -> list[str]:
        """Extract custom instruction sections from request."""
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
                if isinstance(part, str) and part.strip():
                    sections.append(part.strip())

        deduplicated: list[str] = []
        seen: set[str] = set()
        for section in sections:
            normalized = section.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated

    def _render_user_instruction_block(
        self, sections: Sequence[str]
    ) -> dict[str, Any] | None:
        """Render custom instruction sections into a Codex <user_instructions> block."""
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
            combined = [*prepend_sections, default_prompt, *append_sections]
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
                return ""
            fallback_combined = [*prepend_sections, default_prompt, *append_sections]
            result = self._combine_prompt_sections(fallback_combined, deduplicate)
            return result if result is not None else ""

        fallback_combined = [*prepend_sections, default_prompt, *append_sections]
        result = self._combine_prompt_sections(fallback_combined, deduplicate)
        return result if result is not None else ""

    @staticmethod
    def _combine_prompt_sections(
        sections: Sequence[str], deduplicate: bool
    ) -> str | None:
        return PromptResolver._combine_prompt_sections(sections, deduplicate)

    @staticmethod
    def _sanitize_codex_instructions(text: str) -> str:
        return PromptResolver._sanitize_codex_instructions(text)

    def _default_codex_tools(self) -> list[dict[str, Any]]:
        """Return the tool definitions expected by the Codex Responses API."""
        if self._default_tool_schema_override is not None:
            return deepcopy(self._default_tool_schema_override)

        if isinstance(self._tool_schema_resolver, ToolSchemaResolver):
            tools = self._tool_schema_resolver._get_default_tools()
            return [
                (
                    tool.model_dump(exclude_none=True)
                    if hasattr(tool, "model_dump")
                    else dict(tool)
                )
                for tool in tools
            ]

        return []

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
        resolved_capabilities = capabilities or self._resolve_capabilities(request_data)
        return self._request_translator.build_input_items(
            request_data,
            processed_messages,
            effective_model,
            resolved_capabilities,
            custom_instruction_sections=custom_instruction_sections,
        )

    def _is_native_responses_payload(self, request_data: Any) -> bool:
        """Detect if a request payload is in the native Codex/Responses format."""
        if hasattr(request_data, "model_dump"):
            data = request_data.model_dump()
        elif isinstance(request_data, dict):
            data = request_data
        else:
            return False

        if (
            "messages" in data
            and isinstance(data.get("messages"), list)
            and not ("prompt_cache_key" in data or "instructions" in data)
        ):
            return False

        if "input" in data:
            input_val = data.get("input")
            if not isinstance(input_val, list):
                return False
            if input_val:
                first_item = input_val[0]
                if isinstance(first_item, dict):
                    has_responses_structure = "type" in first_item or (
                        "role" in first_item and "content" in first_item
                    )
                    if has_responses_structure:
                        return True

        responses_specific_fields = {"prompt_cache_key", "include", "store"}
        return any(field in data for field in responses_specific_fields)

    def _normalize_processed_messages(
        self, processed_messages: list[Any]
    ) -> list[ProcessedMessage]:
        normalized: list[ProcessedMessage] = []
        for message in processed_messages or []:
            if isinstance(message, ProcessedMessage):
                normalized.append(message)
                continue
            if hasattr(message, "model_dump") and callable(message.model_dump):
                dumped = message.model_dump(exclude_none=True)
                if isinstance(dumped, dict):
                    normalized.append(ProcessedMessage(**dumped))
                    continue
            if isinstance(message, dict):
                normalized.append(ProcessedMessage(**message))
                continue
            role = getattr(message, "role", None)
            content = getattr(message, "content", None)
            if role is not None and content is not None:
                normalized.append(ProcessedMessage(role=role, content=content))
        return normalized

    def _build_codex_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        capabilities: CodexClientCapabilities | None = None,
    ) -> tuple[CodexPayload, str]:
        """Build Codex payload and return payload object with conversation ID."""
        resolved_capabilities = capabilities or self._resolve_capabilities(request_data)
        processed = self._normalize_processed_messages(processed_messages)
        session_id = getattr(request_data, "session_id", None) or str(uuid.uuid4())

        try:
            context = CodexRequestContext(
                request=request_data,
                processed_messages=processed,
                effective_model=effective_model,
                capabilities=resolved_capabilities,
                session_id=session_id,
                metadata=getattr(request_data, "metadata", None),
            )
        except (TypeError, ValidationError) as err:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to validate CodexRequestContext, using model_construct fallback: %s",
                    err,
                    exc_info=True,
                )
            context = CodexRequestContext.model_construct(
                request=request_data,
                processed_messages=processed,
                effective_model=effective_model,
                capabilities=resolved_capabilities,
                session_id=session_id,
                metadata=getattr(request_data, "metadata", None),
            )

        payload = self._payload_builder.build_payload(context)
        return payload, payload.prompt_cache_key

    def _coerce_payload_for_executor(
        self, payload: CodexPayload | dict[str, Any], context: CodexRequestContext
    ) -> CodexPayload:
        if isinstance(payload, CodexPayload):
            return payload

        if isinstance(self._payload_builder, PayloadBuilder):
            try:
                return self._payload_builder._dict_to_payload(payload, context)
            except (TypeError, ValidationError) as err:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to convert payload via _dict_to_payload, using model_construct: %s",
                        err,
                        exc_info=True,
                    )
                return CodexPayload.model_construct(**payload)
        try:
            return CodexPayload.model_validate(payload)
        except (TypeError, ValidationError) as err:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to validate payload, using model_construct: %s",
                    err,
                    exc_info=True,
                )
            return CodexPayload.model_construct(**payload)

    def _select_renderer_key(self, capabilities: CodexClientCapabilities) -> str:
        """Map capability preference to a registered renderer key."""
        renderer_default = (
            self._renderer_default
            if isinstance(self._renderer_default, str)
            else "none"
        )
        preferred_value = capabilities.tool_text_format or renderer_default
        preferred = preferred_value.strip() if isinstance(preferred_value, str) else ""
        if not preferred:
            return renderer_default
        if preferred.lower() in {"default", "inherit"}:
            return renderer_default
        return preferred

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
        headers["conversation_id"] = conversation_id
        headers["session_id"] = conversation_id

    def _stream_retry_delay(self, attempt_index: int) -> float:
        if attempt_index < 0:
            return 0.0
        if not self._stream_retry_backoff:
            return 0.0
        if attempt_index < len(self._stream_retry_backoff):
            return float(self._stream_retry_backoff[attempt_index])
        return float(self._stream_retry_backoff[-1])

    def _should_retry_stream_for_auth_error(
        self, chunk: ProcessedResponse | Any
    ) -> bool:
        if isinstance(self._response_executor, ResponseExecutor):
            return self._response_executor._should_retry_for_auth_error(chunk)
        return False

    @staticmethod
    def _format_tool_results_text(tool_results: list[Any]) -> str:
        texts: list[str] = []
        for result in tool_results:
            text: str | None
            if isinstance(result, ToolExecutionResult):
                text = result.result
            elif isinstance(result, dict):
                value = result.get("result")
                text = value if isinstance(value, str) else None
            else:
                text = None
            if text:
                texts.append(text)
        return "\n\n".join(texts)

    def _format_kilo_response(
        self, response: dict[str, Any], tool_results: list[Any]
    ) -> dict[str, Any]:
        if not tool_results:
            return response

        content = ""
        if response.get("choices"):
            choice = response["choices"][0]
            if "message" in choice:
                content = choice["message"].get("content", "")
            elif "delta" in choice:
                content = choice["delta"].get("content", "")

        tool_results_text = self._format_tool_results_text(tool_results)
        if tool_results_text:
            merged_content = (
                f"{tool_results_text}\n\n{content}" if content else tool_results_text
            )
            if response.get("choices"):
                choice = response["choices"][0]
                if "message" in choice:
                    choice["message"]["content"] = merged_content
                elif "delta" in choice:
                    choice["delta"]["content"] = merged_content

        return response

    async def _format_kilo_stream_response(
        self, stream: AsyncIterator[Any], tool_results: list[Any]
    ) -> AsyncIterator[Any]:
        if tool_results:
            tool_results_text = self._format_tool_results_text(tool_results)
            if tool_results_text:
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

        async for chunk in stream:
            yield chunk

    async def _translate_kilo_tools(
        self,
        message: Any,
        message_content: str,
        session_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {
            "codex_tools": [],
            "proxy_tools": [],
            "mcp_tools": [],
        }
        if self._compatibility_layer is None or not hasattr(
            self._compatibility_layer, "_translate_kilo_tools"
        ):
            return result
        if (
            self._compatibility_layer
            and self._kilo_tool_translator
            and getattr(self._compatibility_layer, "_kilo_translator", None) is None
        ):
            self._compatibility_layer._kilo_translator = self._kilo_tool_translator

        processed_messages = [message]
        tools = await self._compatibility_layer._translate_kilo_tools(
            processed_messages, session_id
        )

        call_id = None
        tool_calls = None
        if isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        elif isinstance(message, ProcessedMessage):
            tool_calls = message.tool_calls

        if tool_calls:
            last_call = tool_calls[-1]
            if isinstance(last_call, dict):
                call_id = last_call.get("id")
            else:
                call_id = getattr(last_call, "id", None)

        for tool in tools.get("codex_tools", []):
            entry = {
                "name": tool.name,
                "arguments": tool.parameters,
            }
            if call_id:
                entry["call_id"] = call_id
            result["codex_tools"].append(entry)

        for tool in tools.get("proxy_tools", []):
            result["proxy_tools"].append(
                {"name": tool.name, "arguments": tool.parameters}
            )

        for tool in tools.get("mcp_tools", []):
            result["mcp_tools"].append(
                {"name": tool.name, "arguments": tool.parameters}
            )

        return result

    def _update_processing_context(
        self, domain_request: Any, updates: dict[str, Any]
    ) -> None:
        if not hasattr(domain_request, "processing_context"):
            return
        if domain_request.processing_context is None:
            domain_request.processing_context = {}

        context = domain_request.processing_context
        if (
            hasattr(context, "update")
            and callable(context.update)
            or isinstance(context, dict)
        ):
            context.update(updates)

    def _resolve_reasoning_effort(
        self, model: str, uri_params: dict[str, Any], request_data: Any
    ) -> str:
        effort = uri_params.get("reasoning_effort")
        if isinstance(effort, list):
            effort = effort[0] if effort else None
        if isinstance(effort, str):
            effort = effort.lower().strip()

        if not effort:
            effort = getattr(request_data, "reasoning_effort", None)
            if isinstance(effort, str):
                effort = effort.lower().strip()

        if not effort:
            effort = self.DEFAULT_REASONING_EFFORT

        if effort not in self.REASONING_EFFORT_LEVELS:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Invalid reasoning_effort '%s', falling back to '%s'. Supported levels: %s",
                    effort,
                    self.DEFAULT_REASONING_EFFORT,
                    ", ".join(self.REASONING_EFFORT_LEVELS),
                )
            effort = self.DEFAULT_REASONING_EFFORT

        if (
            effort == "xhigh"
            and model.lower() not in self._XHIGH_SUPPORTED_MODELS_LOWER
        ):
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Model '%s' does not support 'xhigh' reasoning effort. "
                    "Downgrading to 'high'. Only %s support 'xhigh'.",
                    model,
                    ", ".join(self.XHIGH_SUPPORTED_MODELS),
                )
            effort = "high"

        return effort

    async def _call_codex_responses_api(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        domain_request: Any,
    ) -> Any:
        """Call the Codex-specific Responses API endpoint."""
        capabilities = self._resolve_capabilities(request_data)

        self._update_processing_context(
            domain_request,
            {
                "codex_capabilities": capabilities.to_dict(),
                "bypass_tool_call_reactor": capabilities.bypass_tool_call_reactor,
                "tool_text_format": capabilities.tool_text_format,
            },
        )

        session_id = getattr(domain_request, "session_id", None) or str(uuid.uuid4())
        metadata = None
        if hasattr(domain_request, "metadata"):
            metadata = domain_request.metadata
        elif hasattr(request_data, "metadata"):
            metadata = request_data.metadata

        is_kilocode = False
        tool_results: list[Any] = []
        translated_tools: dict[str, list[Any]] = {
            "codex_tools": [],
            "proxy_tools": [],
            "mcp_tools": [],
        }
        compatibility_state = None
        normalized_messages = self._normalize_processed_messages(processed_messages)
        payload_messages = normalized_messages

        if self._compatibility_layer_enabled and self._session_detector:
            detection_result = await self._session_detector.detect(
                request_data=request_data,
                metadata=metadata,
                session_id=session_id,
                backend=self.backend_type,
            )
            is_kilocode = detection_result.is_kilocode
            self._update_processing_context(
                domain_request,
                {
                    "is_kilocode_client": is_kilocode,
                    "kilocode_detection_method": detection_result.detection_method,
                },
            )

        if self._compatibility_layer_enabled and self._compatibility_layer:
            try:
                context = CodexRequestContext.model_construct(
                    request=request_data,
                    processed_messages=normalized_messages,
                    effective_model=effective_model,
                    capabilities=capabilities,
                    session_id=session_id,
                    metadata=metadata,
                )
                compat_result = await self._compatibility_layer.apply(context)
                compatibility_state = compat_result.state
                is_kilocode = is_kilocode or compat_result.state.is_kilocode
                translated_tools = {
                    "codex_tools": compat_result.codex_tools,
                    "proxy_tools": compat_result.proxy_tools,
                    "mcp_tools": compat_result.mcp_tools,
                }
                tool_results = compat_result.tool_results
                payload_messages = context.processed_messages
            except Exception as exc:
                logger.debug("Compatibility layer apply failed: %s", exc)

        payload, conversation_id = self._build_codex_payload(
            request_data,
            payload_messages,
            effective_model,
            capabilities=capabilities,
        )

        if is_kilocode and translated_tools["codex_tools"]:
            payload_tools = payload.tools
            if not isinstance(payload_tools, list):
                payload_tools = []
                payload.tools = payload_tools

            existing_names: set[str] = set()
            for entry in payload_tools:
                name_value = getattr(entry, "name", None)
                if name_value is None and isinstance(entry, dict):
                    name_value = entry.get("name")
                if isinstance(name_value, str):
                    existing_names.add(name_value)

            for tool in translated_tools["codex_tools"]:
                schema = get_codex_tool_schema(tool.name)
                if not schema:
                    continue
                schema_name = schema.name
                if not isinstance(schema_name, str):
                    continue
                if schema_name in existing_names:
                    continue
                payload_tools.append(schema)
                existing_names.add(schema_name)
                logger.debug("Added Codex-side tool %s to payload", schema_name)

        headers = self._build_codex_headers(conversation_id)
        url = "https://chatgpt.com/backend-api/codex/responses"

        renderer_key = self._select_renderer_key(capabilities)
        request_session_id = (
            getattr(domain_request, "session_id", None) or conversation_id
        )
        stream_val = bool(getattr(request_data, "stream", False))

        executor_metadata: dict[str, object] | None = None
        if isinstance(metadata, dict):
            executor_metadata = dict(metadata)
        if compatibility_state is not None:
            if executor_metadata is None:
                executor_metadata = {}
            executor_metadata["compatibility_state"] = compatibility_state

        executor_context = CodexRequestContext.model_construct(
            request=request_data,
            processed_messages=payload_messages,
            effective_model=effective_model,
            capabilities=capabilities,
            session_id=session_id,
            metadata=executor_metadata,
        )

        use_executor = False
        if self._response_executor and hasattr(self._response_executor, "execute"):
            if not isinstance(self._response_executor, ResponseExecutor):
                use_executor = True
            else:
                use_executor = (
                    getattr(self._response_executor.execute, "__func__", None)
                    is not ResponseExecutor.execute
                )

        payload_obj = (
            self._coerce_payload_for_executor(payload, executor_context)
            if use_executor
            else None
        )

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

                async def _rendered_iterator() -> AsyncIterator[ProcessedResponse]:
                    attempts_used = 0
                    max_retries = max(0, self._stream_retry_limit)
                    if isinstance(self._response_executor, ResponseExecutor):
                        executor_limit = max(0, self._response_executor._max_retries)
                        max_retries = min(max_retries, executor_limit)
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

                                if self._compatibility_layer and compatibility_state:
                                    try:
                                        chunk_wrapper = ProviderStreamChunk(
                                            raw=processed_chunk
                                        )
                                        translated = await self._compatibility_layer.translate_stream_chunk(
                                            chunk_wrapper, compatibility_state
                                        )
                                        processed_chunk = (
                                            translated.raw
                                            if hasattr(translated, "raw")
                                            else translated
                                        )
                                        # Ensure processed_chunk is ProcessedResponse
                                        if not isinstance(processed_chunk, ProcessedResponse):
                                            # Wrap in ProcessedResponse if needed
                                            processed_chunk = ProcessedResponse(
                                                content=processed_chunk if isinstance(processed_chunk, (dict, str, bytes)) else str(processed_chunk)
                                            )
                                    except Exception as exc:
                                        logger.debug(
                                            "Compatibility layer translation failed: %s",
                                            exc,
                                        )

                                # Ensure we yield ProcessedResponse
                                if isinstance(processed_chunk, ProcessedResponse):
                                    yield processed_chunk
                                else:
                                    yield ProcessedResponse(
                                        content=processed_chunk if isinstance(processed_chunk, (dict, str, bytes)) else str(processed_chunk)
                                    )

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
                        if self._compatibility_layer and compatibility_state:
                            with contextlib.suppress(Exception):
                                await self._compatibility_layer.cleanup_state(
                                    compatibility_state
                                )
                        return

                return StreamingResponseEnvelope(
                    content=_rendered_iterator(),
                    media_type="text/event-stream",
                    headers=headers_holder,
                    cancel_callback=cancel_active_stream,
                )

            with OverrideRenderer(renderer_key):
                return await self._handle_non_streaming_response(
                    url,
                    request_payload,
                    request_headers,
                    request_session_id,
                )

        # Only refresh token; reuse same payload to maintain session continuity.
        # No need to rebuild headers or payload on retry.
        for attempt in range(2):
            try:
                if use_executor and payload_obj is not None:
                    response = await self._response_executor.execute(
                        payload_obj, executor_context
                    )
                else:
                    response = await _perform_request(
                        payload.model_dump(exclude_none=True),
                        headers,
                        request_session_id,
                        stream_val,
                    )

                if is_kilocode and tool_results:
                    if stream_val:
                        from collections.abc import AsyncIterator
                        if hasattr(response, "content") and isinstance(response.content, AsyncIterator):
                            formatted_stream = self._format_kilo_stream_response(
                                response.content, tool_results  # type: ignore[arg-type]
                            )
                            return StreamingResponseEnvelope(
                                content=formatted_stream,
                                media_type=getattr(
                                    response, "media_type", "text/event-stream"
                                ),
                                headers=getattr(response, "headers", {}),
                                cancel_callback=getattr(
                                    response, "cancel_callback", None
                                ),
                            )
                    else:
                        if isinstance(response, ResponseEnvelope):
                            if isinstance(response.content, dict):
                                response.content = self._format_kilo_response(
                                    response.content, tool_results
                                )
                        elif isinstance(response, dict):
                            response = self._format_kilo_response(
                                response, tool_results
                            )

                return response
            except httpx.HTTPStatusError as exc:
                try:
                    body = exc.response.json()
                except json.JSONDecodeError:
                    body = exc.response.text
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Codex API request failed with status %s: %s",
                        exc.response.status_code,
                        body,
                    )
                raise HTTPException(status_code=exc.response.status_code, detail=body)
            except HTTPException as exc:
                if exc.status_code == 401 and attempt == 0:
                    # Only refresh token; reuse same payload to maintain session continuity.
                    # No need to rebuild headers or payload on retry.
                    refreshed = await self._refresh_access_token()
                    if refreshed:
                        self._refresh_codex_headers_auth(headers, conversation_id)
                        continue
                raise

        raise RuntimeError("Unexpected fallthrough in Codex response handling.")

    async def _refresh_access_token(self) -> bool:
        refreshed = await self._credential_manager.refresh_access_token()
        if refreshed:
            token = self._credential_manager.get_access_token()
            if token:
                self.api_key = token
            return True
        return False

    # -----------------------------
    # Health Tracking API (stale token handling pattern)
    # -----------------------------
    def is_backend_functional(self) -> bool:
        return self.is_functional and not self._initialization_failed

    def get_validation_errors(self) -> list[str]:
        return self._credential_validation_errors.copy()

    def _fail_init(self, errors: list[str]) -> None:
        self._initialization_failed = True
        self.is_functional = False
        self._credential_validation_errors = errors
        if logger.isEnabledFor(logging.ERROR):
            logger.error("OpenAI Codex initialization failed: %s", "; ".join(errors))

    def _degrade(self, errors: list[str]) -> None:
        self.is_functional = False
        self._credential_validation_errors = errors
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("OpenAI Codex backend degraded: %s", "; ".join(errors))

    def _recover(self) -> None:
        self.is_functional = True
        self._credential_validation_errors = []
        self._last_validation_time = time.time()
        logger.info("OpenAI Codex backend recovered")

    # -----------------------------
    # Validation methods (stale token handling pattern)
    # -----------------------------
    def _validate_credentials_file_exists(self) -> ValidationResult:
        if hasattr(self._credential_manager, "_validate_credentials_file_exists"):
            result = self._credential_manager._validate_credentials_file_exists()
            return cast(ValidationResult, result)
        return ValidationResult.failure("Credential manager not available")

    def _validate_credentials_structure(
        self, credentials: dict[str, Any]
    ) -> ValidationResult:
        if hasattr(self._credential_manager, "_validate_credentials_structure"):
            result = self._credential_manager._validate_credentials_structure(
                credentials
            )
            return cast(ValidationResult, result)
        return ValidationResult.failure("Credential manager not available")

    async def _validate_runtime_credentials(self) -> bool:
        current_time = time.time()
        if current_time - self._last_validation_time < 30:
            return True

        res = self._validate_credentials_file_exists()
        if not res:
            self._credential_validation_errors = res.errors
            return False

        errors = list(res.errors)

        if self._auth_credentials is not None:
            res_struct = self._validate_credentials_structure(self._auth_credentials)
            if not res_struct:
                errors.extend(res_struct.errors)
                self._credential_validation_errors = errors
                return False
        else:
            errors.append("OAuth credentials not loaded in memory")
            self._credential_validation_errors = errors
            return False

        self._credential_validation_errors = []
        self._last_validation_time = current_time
        return True

    # -----------------------------
    # File watching methods (stale token handling pattern)
    # -----------------------------
    def _start_file_watching(self) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get(
            "ENABLE_CODEX_FILE_WATCH", ""
        ).lower() not in {"1", "true", "yes"}:
            logger.debug("Skipping OpenAI Codex credentials watcher under pytest.")
            return
        if self._auth_path is None or self._file_observer is not None:
            return

        try:
            self._file_observer = Observer()
            self._file_observer.daemon = True
            handler = OpenAICredentialsFileHandler(self)
            watch_dir = self._auth_path.parent
            self._file_observer.schedule(handler, str(watch_dir), recursive=False)
            self._file_observer.start()
            logger.debug(
                "Started watching OpenAI Codex credentials directory: %s", watch_dir
            )
        except Exception as exc:
            logger.warning(
                "Failed to start file watching for OpenAI Codex credentials: %s",
                exc,
            )

    def _stop_file_watching(self) -> None:
        observer = self._file_observer
        if observer is None:
            return

        self._file_observer = None

        try:
            observer.stop()
            # 5.0s timeout to allow clean thread termination
            observer.join(timeout=5.0)

            # Verify thread stopped (safe check for BaseObserver which extends Thread)
            if hasattr(observer, "is_alive") and observer.is_alive():  # type: ignore
                logger.warning(
                    "OpenAI Codex file watcher thread did not stop within timeout. "
                    "This may cause issues in parallel test execution."
                )
        except Exception as exc:
            logger.debug("Error stopping OpenAI Codex file watcher: %s", exc)

    def _schedule_credentials_reload(self) -> None:
        if self._shutdown_requested.is_set():
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Skipping reload - shutdown requested")
            return

        if self._reload_scheduling_event.is_set():
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
                try:
                    loaded = await self._load_auth(force_reload=True)
                except TypeError:
                    loaded = await self._load_auth()
                if loaded:
                    if self._auth_credentials is not None:
                        res = self._validate_credentials_structure(
                            self._auth_credentials
                        )
                        if res:
                            self._recover()
                        else:
                            self._degrade(res.errors)
                    else:
                        self._degrade(
                            ["Failed to load credentials despite successful file read"]
                        )
                else:
                    self._degrade(["Failed to reload credentials from file"])
            except Exception as exc:
                logger.error("Error during OpenAI Codex credentials reload: %s", exc)
                self._degrade([f"Credentials reload failed: {exc}"])

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
                        "Failed to schedule OpenAI Codex credentials reload: %s",
                        exc,
                    )
                    self._reload_scheduling_event.clear()

            loop.call_soon_threadsafe(schedule_task)
        except RuntimeError as exc:
            logger.warning(
                "Failed to schedule OpenAI Codex credentials reload: %s", exc
            )
            self._reload_scheduling_event.clear()

    async def _load_auth(self, force_reload: bool = False) -> bool:
        loaded = await self._credential_manager._load_auth(force_reload=force_reload)
        loaded_bool = bool(loaded)
        if loaded_bool:
            token = self._credential_manager.get_access_token()
            if isinstance(token, str) and token:
                self.api_key = token
        return loaded_bool

    async def initialize(self, **kwargs: Any) -> None:  # type: ignore[override]
        """Initialize backend with enhanced validation using stale token handling pattern."""
        logger.info("Initializing OpenAI Codex backend with enhanced validation.")

        self._refresh_settings_from_overrides()

        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._event_loop = None

        base = kwargs.get("openai_api_base_url") or kwargs.get("api_base_url")
        if isinstance(base, str) and base:
            self.api_base_url = base

        self._enable_codex_backend_debugging_override = kwargs.get(
            "enable_openai_codex_backend_debugging_override",
            self._enable_codex_backend_debugging_override,
        )
        backend_config = getattr(self.config.backends, "openai_codex", None)
        if backend_config and hasattr(backend_config, "extra"):
            extras = (
                backend_config.extra
                if isinstance(backend_config.extra, Mapping)
                else {}
            )
            if extras.get("enable_openai_codex_backend_debugging_override"):
                self._enable_codex_backend_debugging_override = True

        dir_override = kwargs.get("openai_codex_path")
        if isinstance(dir_override, str) and dir_override:
            self._oauth_dir_override = Path(dir_override)

        res_file = self._validate_credentials_file_exists()
        if not res_file:
            self._fail_init(res_file.errors)
            return

        if not await self._load_auth():
            self._fail_init(["Failed to load credentials despite validation passing"])
            return

        if self._auth_credentials is not None:
            res_struct = self._validate_credentials_structure(self._auth_credentials)
            if not res_struct:
                self._fail_init(res_struct.errors)
                return
        else:
            self._fail_init(["OAuth credentials are None after loading"])
            return

        self._start_file_watching()
        self.is_functional = True
        self._last_validation_time = time.time()
        logger.info("Credentials file validation passed for %s.", self.name)

    async def _prepare_payload(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
    ) -> dict[str, Any]:
        payload = await super()._prepare_payload(
            request_data, processed_messages, effective_model
        )
        if "model" in payload and isinstance(payload["model"], str):
            payload["model"] = strip_vendor_prefix(
                payload["model"], OPENAI_VENDOR_PREFIX
            )
        return payload

    async def chat_completions(  # type: ignore[override]
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        cancellation_token: SessionKey | None = None,
        cancellation_coordinator: (
            Any | None
        ) = None,  # ISessionCancellationCoordinator | None
        **kwargs: Any,
    ):
        # Structural enforcement: check cancellation immediately if coordinator and token provided
        if cancellation_coordinator is not None and cancellation_token is not None:
            cancellation_coordinator.ensure_not_cancelled(cancellation_token)
        uri_params: dict[str, Any] = {}
        model_for_parsing = effective_model
        if ":" in model_for_parsing and not model_for_parsing.startswith("openai/"):
            model_for_parsing = model_for_parsing.split(":", 1)[1]

        try:
            parsed = parse_model_with_params(model_for_parsing)
            _, parsed_model, uri_params = (
                parsed.backend_type,
                parsed.model_name,
                parsed.uri_params,
            )
            effective_model = strip_vendor_prefix(parsed_model, OPENAI_VENDOR_PREFIX)
        except Exception as exc:
            logger.debug("Failed to parse model URI params: %s", exc)
            if ":" in effective_model:
                effective_model = effective_model.split(":", 1)[1]
            effective_model = strip_vendor_prefix(effective_model, OPENAI_VENDOR_PREFIX)
            if "?" in effective_model:
                effective_model = effective_model.split("?", 1)[0]

        resolved_reasoning_effort = self._resolve_reasoning_effort(
            effective_model, uri_params, request_data
        )
        if hasattr(request_data, "__dict__"):
            request_data._codex_resolved_reasoning_effort = resolved_reasoning_effort
        elif isinstance(request_data, dict):
            request_data["_codex_resolved_reasoning_effort"] = resolved_reasoning_effort

        if not self._enable_codex_backend_debugging_override:
            logger.warning(
                "Blocked attempt to use OpenAI Codex backend without debugging override flag."
            )
            raise HTTPException(
                status_code=403,
                detail=(
                    "Forbidden: This backend is reserved for internal development and "
                    "debugging. To enable it, use the "
                    "--enable-openai-codex-backend-debugging-override CLI flag. "
                    "See documentation for legal disclaimers and usage restrictions."
                ),
            )

        ok = await self._validate_runtime_credentials()
        errors = self.get_validation_errors()
        if not ok:
            self._degrade(errors)
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "openai_codex_credentials_invalid",
                    "message": "OpenAI Codex credentials validation failed: "
                    f"{'; '.join(errors)}",
                    "details": {
                        "backend": self.name,
                        "validation_errors": errors,
                        "suggestion": "Please check your OAuth credentials file and ensure it contains valid tokens.access_token or OPENAI_API_KEY",
                    },
                },
            )

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
            except Exception as exc:
                if (
                    isinstance(exc, AuthenticationError | HTTPException)
                    and hasattr(exc, "status_code")
                    and exc.status_code in (401, 403)
                ):
                    self._degrade([f"Authentication failed: {exc!s}"])
                raise

        try:
            result = await super().chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                identity=identity,
                **kwargs,
            )
            if not self.is_functional:
                self._recover()
            return result
        except Exception as exc:
            if (
                isinstance(exc, AuthenticationError | HTTPException)
                and hasattr(exc, "status_code")
                and exc.status_code in (401, 403)
            ):
                self._degrade([f"Authentication failed: {exc!s}"])
            raise

    async def _handle_non_streaming_response(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None,
        session_id: str,
    ) -> ResponseEnvelope:
        """Override to ensure compatibility state cleanup for non-streaming responses."""
        compatibility_state = None

        # Extract compatibility state from payload's executor metadata
        # This was added in _call_codex_responses_api before calling this method
        if isinstance(payload, dict):
            metadata = payload.get("metadata", {})
            if isinstance(metadata, dict):
                compatibility_state = metadata.get("compatibility_state")

        try:
            # Call parent implementation
            result = await super()._handle_non_streaming_response(
                url, payload, headers, session_id
            )

            # Clean up compatibility state to prevent memory leaks
            if self._compatibility_layer and compatibility_state:
                try:
                    await self._compatibility_layer.cleanup_state(compatibility_state)
                except Exception as exc:
                    logger.debug(
                        "Failed to cleanup compatibility state for non-streaming response: %s",
                        exc,
                    )

            return result

        except Exception:
            # Ensure cleanup even if parent fails
            if self._compatibility_layer and compatibility_state:
                try:
                    await self._compatibility_layer.cleanup_state(compatibility_state)
                except Exception as exc:
                    logger.debug(
                        "Failed to cleanup compatibility state during error handling: %s",
                        exc,
                    )
            raise

    def get_available_models(self) -> list[str]:
        return [
            add_vendor_prefix(m, OPENAI_VENDOR_PREFIX)
            for m in self.SUPPORTED_CODEX_MODELS
        ]

    def __del__(self) -> None:
        self._stop_file_watching()

    async def shutdown(self) -> None:
        """Stop background file watchers to avoid thread leaks."""
        # 1. Signal shutdown to prevent new tasks
        self._shutdown_requested.set()

        # 2. Cancel local pending reload tasks
        pending_task: asyncio.Future[Any] | None = None
        with self._reload_task_lock:
            pending_task = self._pending_reload_task
            self._pending_reload_task = None
        if pending_task is not None and not pending_task.done():
            pending_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pending_task
        self._reload_scheduling_event.clear()

        # 3. Stop local file watcher synchronously
        self._stop_file_watching()

        # 4. Stop delegated credential manager
        if hasattr(self._credential_manager, "shutdown"):
            await self._credential_manager.shutdown()


backend_registry.register_backend("openai-codex", OpenAICodexConnector)
