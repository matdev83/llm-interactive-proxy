"""TDD tests for OpenAI Codex connector verbosity resolution and payload."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.catalog.types import (
    CodexModelCatalog,
    CodexModelReasoningProfile,
)
from src.connectors.openai_codex.contracts import (
    CanonicalChatRequest,
    CodexConnectorSettings,
    CodexRequestContext,
)
from src.connectors.openai_codex.payload import PayloadBuilder
from src.core.domain.chat import ChatMessage


def _settings() -> CodexConnectorSettings:
    return CodexConnectorSettings(
        default_capabilities=CodexClientCapabilities(),
        agent_overrides={},
        renderer={
            "default": "none",
            "fallback": "summary",
            "aliases": {},
            "modules": {},
        },
        prompt={
            "template": None,
            "prepend": [],
            "append": [],
            "deduplicate": True,
            "fallback_to_default": True,
        },
        tool_schema={"base_tools": None, "custom_tools": []},
        streaming={"max_retries": 2, "retry_backoff_seconds": (0.5, 1.5, 3.0)},
        compatibility_layer={
            "enabled": False,
            "detection": {"cache_ttl_seconds": 3600, "heuristic_threshold": 2},
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
        websocket={"enabled": False},
    )


def _catalog_with_verbosity() -> CodexModelCatalog:
    profiles = {
        "gpt-5.4-mini": CodexModelReasoningProfile(
            slug="gpt-5.4-mini",
            default_reasoning_level="medium",
            supported_reasoning_levels=("low", "medium", "high"),
            support_verbosity=True,
            default_verbosity="low",
        ),
        "no-verbosity-model": CodexModelReasoningProfile(
            slug="no-verbosity-model",
            default_reasoning_level="medium",
            supported_reasoning_levels=("low", "medium", "high"),
            support_verbosity=False,
        ),
    }
    return CodexModelCatalog(
        profiles=profiles,
        reasoning_effort_order=("low", "medium", "high"),
        default_reasoning_effort="medium",
    )


def _builder(connector: MagicMock) -> PayloadBuilder:
    mock_translator = MagicMock()
    mock_translator.translate_messages.return_value = []
    mock_prompt_resolver = MagicMock()
    mock_prompt_resolver.resolve_system_prompt.return_value = None
    mock_tool_resolver = MagicMock()
    mock_tool_resolver.resolve_tool_schema.return_value = []
    return PayloadBuilder(
        connector=connector,
        request_translator=mock_translator,
        prompt_resolver=mock_prompt_resolver,
        tool_schema_resolver=mock_tool_resolver,
        settings=_settings(),
        message_to_text_converter=lambda m: getattr(m, "content", ""),
    )


class TestCodexResolveVerbosity:
    def test_resolve_verbosity_from_uri_params(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        # Bind the real method
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
        )
        assert bound("gpt-5.4-mini", {"verbosity": "high"}, request) == "high"

    def test_resolve_verbosity_from_request_field(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
            verbosity="low",
        )
        assert bound("gpt-5.4-mini", {}, request) == "low"

    def test_resolve_verbosity_prefers_resolved_canonical_over_uri(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
            verbosity="high",
        )

        assert bound("gpt-5.4-mini", {"verbosity": "low"}, request) == "high"

    def test_resolve_verbosity_none_when_unset(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
        )
        assert bound("gpt-5.4-mini", {}, request) is None

    def test_resolve_verbosity_none_when_model_unsupported(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="no-verbosity-model",
            verbosity="high",
        )
        assert bound("no-verbosity-model", {}, request) is None

    def test_resolve_verbosity_invalid_value_returns_none(self) -> None:
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
            verbosity="extreme",
        )
        assert bound("gpt-5.4-mini", {}, request) is None

    def test_resolve_verbosity_invalid_uri_falls_back_to_body(self) -> None:
        """Invalid URI verbosity must not block a valid body value."""
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
            verbosity="low",
        )
        assert bound("gpt-5.4-mini", {"verbosity": "extreme"}, request) == "low"

    def test_resolve_verbosity_invalid_body_falls_back_to_extra_body(
        self,
    ) -> None:
        """Invalid request.verbosity must not block a valid extra_body value."""
        from src.connectors.openai_codex import OpenAICodexConnector

        connector = MagicMock(spec=OpenAICodexConnector)
        connector._catalog = _catalog_with_verbosity()
        bound = OpenAICodexConnector._resolve_verbosity.__get__(
            connector, OpenAICodexConnector
        )
        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="hi")],
            model="gpt-5.4-mini",
            verbosity="extreme",
            extra_body={"verbosity": "medium"},
        )
        assert bound("gpt-5.4-mini", {}, request) == "medium"


class TestCodexPayloadVerbosity:
    def test_payload_builder_emits_text_verbosity(self) -> None:
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"
        builder = _builder(mock_connector)

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.4-mini",
        )
        object.__setattr__(request, "_codex_resolved_verbosity", "low")

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="gpt-5.4-mini",
            session_id="test-session-1",
        )
        payload = builder.build_payload(context)
        assert payload.text is not None
        assert payload.text.verbosity == "low"

    def test_payload_builder_omits_text_when_verbosity_unset(self) -> None:
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"
        builder = _builder(mock_connector)

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.4-mini",
        )
        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="gpt-5.4-mini",
            session_id="test-session-2",
        )
        payload = builder.build_payload(context)
        assert payload.text is None

    def test_payload_builder_omits_text_when_resolved_verbosity_is_none(
        self,
    ) -> None:
        """Catalog/invalid gate must not fall back to request.verbosity."""
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"
        builder = _builder(mock_connector)

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="no-verbosity-model",
            verbosity="high",
        )
        object.__setattr__(request, "_codex_resolved_verbosity", None)

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="no-verbosity-model",
            session_id="test-session-3",
            metadata={"verbosity": "medium"},
        )
        payload = builder.build_payload(context)
        assert payload.text is None

    def test_passthrough_omits_text_when_resolved_verbosity_is_none(self) -> None:
        """Passthrough text.verbosity must not bypass the catalog gate."""
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = True
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"
        builder = _builder(mock_connector)

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="no-verbosity-model",
            extra_body={
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Hello"}],
                    }
                ],
                "text": {"verbosity": "high"},
            },
        )
        object.__setattr__(request, "_codex_resolved_verbosity", None)

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(codex_passthrough=True),
            effective_model="no-verbosity-model",
            session_id="test-session-passthrough-gate",
        )
        payload = builder.build_payload(context)
        assert payload.text is None

    def test_passthrough_prefers_resolved_verbosity_over_payload_text(self) -> None:
        """Resolved verbosity must win over passthrough text.verbosity."""
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = True
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"
        builder = _builder(mock_connector)

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.4-mini",
            extra_body={
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Hello"}],
                    }
                ],
                "text": {"verbosity": "high"},
            },
        )
        object.__setattr__(request, "_codex_resolved_verbosity", "low")

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(codex_passthrough=True),
            effective_model="gpt-5.4-mini",
            session_id="test-session-passthrough-resolved",
        )
        payload = builder.build_payload(context)
        assert payload.text is not None
        assert payload.text.verbosity == "low"
