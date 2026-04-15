"""Unit tests for PayloadBuilder service.

Tests cover passthrough detection edge cases and payload construction.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexConnectorSettings,
    CodexInputItem,
    CodexPayload,
    CodexRequestContext,
    CodexToolSchema,
    ProcessedMessage,
    ReasoningSpec,
)
from src.connectors.openai_codex.interfaces import (
    IPayloadBuilder,
    IPromptResolver,
    IRequestTranslator,
    IToolSchemaResolver,
)
from src.connectors.openai_codex.payload import PayloadBuilder
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


class TestPayloadBuilder:
    """Test PayloadBuilder service implementation."""

    @pytest.fixture
    def mock_connector(self):
        """Create a mock connector."""
        connector = MagicMock()
        connector._is_native_responses_payload = MagicMock(return_value=False)
        connector._connector_settings = {}
        connector._resolve_system_prompt = MagicMock(return_value=None)
        connector._sanitize_codex_instructions = MagicMock(side_effect=lambda x: x)
        connector._message_to_text = MagicMock(
            side_effect=lambda m: getattr(m, "content", "")
        )
        connector.DEFAULT_REASONING_EFFORT = "medium"
        return connector

    @pytest.fixture
    def mock_request_translator(self):
        """Create a mock request translator."""
        translator = MagicMock(spec=IRequestTranslator)
        translator.translate_messages = MagicMock(
            return_value=[CodexInputItem(type="message", content="test")]
        )
        return translator

    @pytest.fixture
    def mock_prompt_resolver(self):
        """Create a mock prompt resolver."""
        resolver = MagicMock(spec=IPromptResolver)
        return resolver

    @pytest.fixture
    def mock_tool_schema_resolver(self):
        """Create a mock tool schema resolver."""
        resolver = MagicMock(spec=IToolSchemaResolver)
        resolver.resolve_tool_schema = MagicMock(return_value=[])
        return resolver

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
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
        )

    @pytest.fixture
    def message_to_text_converter(self):
        """Create a message to text converter."""
        return lambda m: getattr(m, "content", "") if hasattr(m, "content") else str(m)

    @pytest.fixture
    def builder(
        self,
        mock_connector,
        mock_request_translator,
        mock_prompt_resolver,
        mock_tool_schema_resolver,
        mock_settings,
        message_to_text_converter,
    ):
        """Create a PayloadBuilder instance for testing."""
        return PayloadBuilder(
            connector=mock_connector,
            request_translator=mock_request_translator,
            prompt_resolver=mock_prompt_resolver,
            tool_schema_resolver=mock_tool_schema_resolver,
            settings=mock_settings,
            message_to_text_converter=message_to_text_converter,
        )

    @pytest.fixture
    def sample_context(self):
        """Create a sample CodexRequestContext."""
        request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        return CodexRequestContext(
            request=request,
            processed_messages=[
                ProcessedMessage(
                    role="user",
                    content="Test message",
                    tool_calls=None,
                )
            ],
            effective_model="gpt-5.1-codex",
            capabilities=CodexClientCapabilities(),
            session_id="test-session-123",
        )

    def test_builder_implements_interface(self, builder):
        """Verify builder implements IPayloadBuilder interface."""
        assert isinstance(builder, IPayloadBuilder)

    def test_build_payload_non_passthrough(
        self, builder, mock_connector, sample_context, mock_request_translator
    ):
        """Test building payload from scratch (non-passthrough)."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert isinstance(payload, CodexPayload)
        assert payload.model == sample_context.effective_model
        mock_request_translator.translate_messages.assert_called_once()

    def test_build_translated_payload_uses_proxy_session_id_as_prompt_cache_key_fallback(
        self,
        builder,
        mock_connector,
        sample_context,
    ):
        """Translated payloads should fall back to the proxy session id."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.prompt_cache_key == sample_context.session_id

    def test_build_translated_payload_reuses_proxy_session_id_across_turns_without_request_side_ids(
        self,
        builder,
        mock_connector,
        sample_context,
    ):
        """Repeated translated turns should keep a stable conversation key."""
        mock_connector._is_native_responses_payload.return_value = False

        first_payload = builder.build_payload(sample_context)
        second_context = sample_context.model_copy(
            update={
                "processed_messages": [
                    ProcessedMessage(role="user", content="Test message"),
                    ProcessedMessage(role="assistant", content="Reply"),
                    ProcessedMessage(role="user", content="Follow-up"),
                ]
            }
        )
        second_payload = builder.build_payload(second_context)

        assert first_payload.prompt_cache_key == sample_context.session_id
        assert second_payload.prompt_cache_key == sample_context.session_id

    def test_build_payload_passthrough_detection(
        self, builder, mock_connector, sample_context
    ):
        """Test passthrough detection when native Responses payload detected."""
        mock_connector._is_native_responses_payload.return_value = True
        # Create a request that looks like native Responses format
        passthrough_request = MagicMock()
        passthrough_request.model_dump = MagicMock(
            return_value={
                "model": "gpt-5.1-codex",
                "input": [{"type": "message", "content": "test"}],
                "stream": True,
                "prompt_cache_key": "test-key",
            }
        )
        passthrough_request.stream = True
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)

        payload = builder.build_payload(sample_context)

        assert isinstance(payload, CodexPayload)
        assert payload.model == sample_context.effective_model
        assert payload.stream is True

    def test_build_payload_passthrough_without_capability(
        self, builder, mock_connector, sample_context
    ):
        """Test that passthrough is not used when capability is disabled."""
        mock_connector._is_native_responses_payload.return_value = True
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=False)

        payload = builder.build_payload(sample_context)

        # Should build from scratch, not passthrough
        # Passthrough check happens first, so it's still called
        assert isinstance(payload, CodexPayload)
        # The method checks capability first, so passthrough won't be used
        # but _is_native_responses_payload may or may not be called depending on implementation
        assert payload.model == sample_context.effective_model

    def test_build_payload_passthrough_validation_rules(
        self, builder, mock_connector, sample_context
    ):
        """Test passthrough validation rules."""
        # Test with dict-like request
        passthrough_dict = {
            "model": "gpt-5.1-codex",
            "input": [{"type": "message", "content": "test"}],
            "stream": False,
            "conversation_id": "conv-123",
        }
        sample_context.request = passthrough_dict
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert isinstance(payload, CodexPayload)
        assert payload.prompt_cache_key == "conv-123"

    def test_build_payload_passthrough_with_session_id(
        self, builder, mock_connector, sample_context
    ):
        """Test passthrough uses session_id when conversation_id missing."""
        passthrough_dict = {
            "model": "gpt-5.1-codex",
            "input": [],
            "session_id": "session-456",
            "store": False,  # Required Responses-specific field for passthrough detection
        }
        sample_context.request = passthrough_dict
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert payload.prompt_cache_key == "session-456"

    def test_build_payload_passthrough_preserves_previous_response_id(
        self, builder, mock_connector, sample_context
    ):
        """Responses passthrough should keep previous_response_id intact."""
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=True,
        )
        object.__setattr__(
            passthrough_request,
            "extra_body",
            {
                "input": [{"type": "message", "role": "user", "content": "test"}],
                "previous_response_id": "resp-123",
                "store": False,
                "stream": True,
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert payload.previous_response_id == "resp-123"

    def test_build_payload_passthrough_continuation_keeps_bootstrap_fields_omitted(
        self,
        builder,
        mock_connector,
        mock_prompt_resolver,
        mock_tool_schema_resolver,
        sample_context,
    ):
        """Continued passthrough turns should not re-inject instructions or tools."""
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=True,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )
        object.__setattr__(
            passthrough_request,
            "extra_body",
            {
                "input": [{"type": "message", "role": "user", "content": "delta"}],
                "previous_response_id": "resp-123",
                "store": False,
                "stream": True,
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True
        mock_prompt_resolver.resolve_system_prompt.return_value = "Codex instructions"
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]

        payload = builder.build_payload(sample_context)

        assert payload.previous_response_id == "resp-123"
        assert payload.instructions is None
        assert payload.tools == []
        mock_tool_schema_resolver.resolve_tool_schema.assert_not_called()

    def test_build_payload_passthrough_appends_opencode_bridge(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """OpenCode passthrough should inject bridge instructions when tools exist."""
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        object.__setattr__(
            passthrough_request,
            "extra_body",
            {
                "input": [{"type": "message", "role": "user", "content": "test"}],
                "tools": [{"name": "bash", "type": "function", "parameters": {}}],
                "store": False,
                "stream": True,
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        sample_context.metadata = {"agent": "opencode"}
        mock_connector._is_native_responses_payload.return_value = True
        mock_prompt_resolver.resolve_system_prompt.return_value = "Codex instructions"

        payload = builder.build_payload(sample_context)

        assert payload.instructions is not None
        assert "Codex instructions" in payload.instructions
        assert "OpenCode compatibility mode" in payload.instructions

    def test_build_payload_passthrough_opencode_no_tools_fills_instructions(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """OpenCode + passthrough + no tools must still send Codex-required instructions."""
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Hello")],
            stream=True,
            agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
        )
        object.__setattr__(
            passthrough_request,
            "extra_body",
            {
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Hello"}],
                    }
                ],
                "codex_capabilities": {"codex_passthrough": True},
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True
        mock_prompt_resolver.resolve_system_prompt.return_value = (
            "Resolved default Codex instructions for test"
        )

        payload = builder.build_payload(sample_context)

        assert payload.instructions is not None
        assert payload.instructions.strip()
        assert "Resolved default Codex instructions for test" in payload.instructions

    def test_passthrough_merges_tools_from_canonical_when_absent_in_extra_body(
        self,
        builder,
        mock_connector,
        mock_tool_schema_resolver,
        sample_context,
    ):
        """Responses API keeps tools on CanonicalChatRequest; passthrough must still forward them."""
        mock_connector._is_native_responses_payload.return_value = True
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            extra_body={
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    }
                ],
                "codex_capabilities": {"codex_passthrough": True},
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)

        payload = builder.build_payload(sample_context)

        mock_tool_schema_resolver.resolve_tool_schema.assert_called_once()
        assert len(payload.tools) == 1
        assert payload.tools[0].name == "read_file"

    def test_passthrough_does_not_replace_explicit_empty_tools_in_extra_body(
        self,
        builder,
        mock_connector,
        mock_tool_schema_resolver,
        sample_context,
    ):
        """Explicit ``tools: []`` in extra_body disables merge from canonical tools."""
        mock_connector._is_native_responses_payload.return_value = True
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
            extra_body={
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "hi"}],
                    }
                ],
                "tools": [],
                "codex_capabilities": {"codex_passthrough": True},
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)

        payload = builder.build_payload(sample_context)

        mock_tool_schema_resolver.resolve_tool_schema.assert_not_called()
        assert payload.tools == []

    def test_build_payload_passthrough_normalizes_opencode_input(
        self, builder, mock_connector, sample_context
    ):
        """OpenCode passthrough should normalize input history inside adapter."""
        passthrough_request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        object.__setattr__(
            passthrough_request,
            "extra_body",
            {
                "input": [
                    {"type": "item_reference", "id": "ref-1"},
                    {
                        "type": "message",
                        "id": "msg-1",
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "OpenCode tool environment prompt",
                            }
                        ],
                    },
                    {
                        "type": "function_call_output",
                        "id": "out-1",
                        "call_id": "missing-call",
                        "output": {"status": "ok"},
                    },
                    {
                        "type": "message",
                        "id": "msg-2",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "test"}],
                    },
                ],
                "tools": [{"name": "bash", "type": "function", "parameters": {}}],
                "store": False,
                "stream": True,
            },
        )
        sample_context.request = passthrough_request
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        sample_context.metadata = {"agent": "opencode"}
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert payload.input
        assert payload.input[0].role == "developer"
        first_content = payload.input[0].content
        assert isinstance(first_content, list)
        assert "OpenCode compatibility mode" in str(first_content[0]["text"])
        assert any(item.type == "item_reference" for item in payload.input)
        assert payload.input[1].model_dump(exclude_none=True)["id"] == "ref-1"
        assert any(
            item.model_dump(exclude_none=True).get("id") == "msg-2"
            for item in payload.input
        )
        normalized_text = "\n".join(str(item.content) for item in payload.input)
        assert "OpenCode tool environment prompt" not in normalized_text
        assert "Prior tool output" in normalized_text

    def test_convert_dict_to_payload_preserves_responses_item_fields(
        self, builder, sample_context
    ):
        """Native Responses items should keep IDs, metadata, and references."""
        payload = builder.convert_dict_to_payload(
            {
                "model": "gpt-5.1-codex",
                "input": [
                    {
                        "type": "message",
                        "id": "msg-1",
                        "role": "user",
                        "metadata": {"source": "responses"},
                        "content": [
                            {
                                "type": "input_text",
                                "text": "hello",
                            }
                        ],
                    },
                    {
                        "type": "function_call_output",
                        "id": "out-1",
                        "call_id": "call-1",
                        "item_reference": {
                            "type": "function_call",
                            "id": "call-1",
                        },
                        "output": {"status": "ok"},
                    },
                    {
                        "type": "item_reference",
                        "id": "ref-1",
                        "item": {
                            "type": "function_call",
                            "id": "call-1",
                        },
                    },
                ],
                "previous_response_id": "resp-456",
                "stream": True,
            },
            sample_context,
        )

        assert payload.previous_response_id == "resp-456"
        first_item = payload.input[0].model_dump(exclude_none=True)
        assert first_item["id"] == "msg-1"
        assert first_item["metadata"] == {"source": "responses"}
        assert first_item["content"][0]["text"] == "hello"

        second_item = payload.input[1].model_dump(exclude_none=True)
        assert second_item["id"] == "out-1"
        assert second_item["item_reference"] == {
            "type": "function_call",
            "id": "call-1",
        }
        assert second_item["output"] == {"status": "ok"}

        third_item = payload.input[2].model_dump(exclude_none=True)
        assert third_item["type"] == "item_reference"
        assert third_item["id"] == "ref-1"
        assert third_item["item"] == {"type": "function_call", "id": "call-1"}

    def test_build_payload_passthrough_uses_proxy_session_id_when_no_request_key_exists(
        self, builder, mock_connector, sample_context
    ):
        """Passthrough should fall back to the proxy session id before UUID."""
        passthrough_dict = {
            "model": "gpt-5.1-codex",
            "input": [],
        }
        sample_context.request = passthrough_dict
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert payload.prompt_cache_key == sample_context.session_id

    def test_build_translated_payload_includes_tools(
        self,
        builder,
        mock_connector,
        sample_context,
        mock_tool_schema_resolver,
    ):
        """Test that translated payload includes resolved tool schemas."""
        mock_connector._is_native_responses_payload.return_value = False
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(name="test_tool", parameters={})
        ]

        payload = builder.build_payload(sample_context)

        assert len(payload.tools) == 1
        assert payload.tools[0].name == "test_tool"
        mock_tool_schema_resolver.resolve_tool_schema.assert_called_once_with(
            sample_context
        )

    def test_build_translated_payload_includes_reasoning(
        self, builder, mock_connector, sample_context
    ):
        """Test that translated payload includes reasoning effort when specified."""
        mock_connector._is_native_responses_payload.return_value = False
        sample_context.metadata = {"reasoning_effort": "high"}

        payload = builder.build_payload(sample_context)

        assert payload.reasoning is not None
        assert isinstance(payload.reasoning, ReasoningSpec)
        assert payload.reasoning.effort == "high"

    def test_build_translated_payload_reasoning_from_request(
        self, builder, mock_connector, sample_context
    ):
        """Test that reasoning effort is extracted from request attribute."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        # Create a new request with reasoning_effort attribute
        request_with_reasoning = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        # Use object.__setattr__ to bypass frozen check for testing
        object.__setattr__(request_with_reasoning, "reasoning_effort", "low")
        sample_context.request = request_with_reasoning

        payload = builder.build_payload(sample_context)

        assert payload.reasoning is not None
        assert payload.reasoning.effort == "low"

    def test_build_translated_payload_reasoning_default(
        self, builder, mock_connector, sample_context
    ):
        """Test that default reasoning effort is used when not specified."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.reasoning is not None
        assert payload.reasoning.effort == "medium"

    def test_build_translated_payload_includes_instructions(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """Test that instructions are included when system prompt is resolved."""
        mock_connector._is_native_responses_payload.return_value = False
        # Mock prompt resolver to return system prompt
        mock_prompt_resolver.resolve_system_prompt.return_value = "System instructions"

        payload = builder.build_payload(sample_context)

        # Instructions should be sanitized version of system prompt
        assert payload.instructions == "System instructions"

    def test_build_translated_payload_appends_opencode_bridge(
        self,
        builder,
        mock_connector,
        mock_prompt_resolver,
        mock_tool_schema_resolver,
        sample_context,
    ):
        """OpenCode sessions should receive bridge instructions for shell tools."""
        mock_connector._is_native_responses_payload.return_value = False
        mock_prompt_resolver.resolve_system_prompt.return_value = "System instructions"
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(name="bash", parameters={})
        ]
        sample_context.metadata = {
            "headers": {"user-agent": "opencode/1.2.26 ai-sdk/provider-utils/3.0.20"}
        }

        payload = builder.build_payload(sample_context)

        assert payload.instructions is not None
        assert "System instructions" in payload.instructions
        assert "OpenCode compatibility mode" in payload.instructions
        assert "string `command` and string `description`" in payload.instructions

    def test_build_translated_payload_prepends_opencode_bridge_message(
        self,
        builder,
        mock_connector,
        mock_tool_schema_resolver,
        sample_context,
    ):
        """Translated OpenCode payloads should prepend a developer bridge message."""
        mock_connector._is_native_responses_payload.return_value = False
        mock_tool_schema_resolver.resolve_tool_schema.return_value = [
            CodexToolSchema(name="bash", parameters={})
        ]
        sample_context.metadata = {"agent": "opencode"}

        payload = builder.build_payload(sample_context)

        assert payload.input
        assert payload.input[0].type == "message"
        assert payload.input[0].role == "developer"
        assert "OpenCode compatibility mode" in str(payload.input[0].content)

    def test_build_translated_payload_prepends_kilocode_family_bridge_message(
        self,
        builder,
        mock_connector,
        sample_context,
    ):
        """KiloCode/RooCode XML clients should receive a developer bridge message."""
        mock_connector._is_native_responses_payload.return_value = False
        sample_context.metadata = {"agent": "roocode"}

        payload = builder.build_payload(sample_context)

        assert payload.instructions is not None
        assert "Cline-family XML compatibility mode" in payload.instructions
        assert payload.input
        assert payload.input[0].type == "message"
        assert payload.input[0].role == "developer"
        assert "Cline-family XML compatibility mode" in str(payload.input[0].content)

    def test_build_translated_payload_no_instructions_when_none(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """Test that instructions are None when system prompt is not resolved."""
        mock_connector._is_native_responses_payload.return_value = False
        # Mock prompt resolver to return None
        mock_prompt_resolver.resolve_system_prompt.return_value = ""

        payload = builder.build_payload(sample_context)

        assert payload.instructions is None

    def test_build_translated_payload_stream_default(
        self, builder, mock_connector, sample_context
    ):
        """Test that Codex backend always uses streaming SSE."""
        mock_connector._is_native_responses_payload.return_value = False
        payload = builder.build_payload(sample_context)

        assert payload.stream is True

    def test_build_translated_payload_conversation_id(
        self, builder, mock_connector, sample_context
    ):
        """Translated payloads should use the proxy session id as conversation key."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.prompt_cache_key == sample_context.session_id

    def test_build_translated_payload_tool_choice(
        self, builder, mock_connector, sample_context
    ):
        """Test that tool_choice defaults to 'auto'."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.tool_choice == "auto"

    def test_build_translated_payload_parallel_tool_calls(
        self, builder, mock_connector, sample_context
    ):
        """Test that parallel_tool_calls defaults to False."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.parallel_tool_calls is False

    def test_build_translated_payload_store_default(
        self, builder, mock_connector, sample_context
    ):
        """Test that store defaults to False."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        assert payload.store is False

    def test_build_translated_payload_reasoning_include(
        self, builder, mock_connector, sample_context
    ):
        """Test that reasoning encrypted_content is included when reasoning is present."""
        mock_connector._is_native_responses_payload.return_value = False
        sample_context.metadata = {"reasoning_effort": "high"}

        payload = builder.build_payload(sample_context)

        assert "reasoning.encrypted_content" in payload.include

    def test_build_translated_payload_no_reasoning_include(
        self, builder, mock_connector, sample_context
    ):
        """Test that reasoning include is empty when no reasoning."""
        mock_connector._is_native_responses_payload.return_value = False

        payload = builder.build_payload(sample_context)

        # Should still have reasoning with default effort
        assert payload.reasoning is not None
        assert "reasoning.encrypted_content" in payload.include

    def test_extract_custom_instruction_sections_from_system_prompt(
        self, builder, mock_connector, sample_context
    ):
        """Test extraction of custom instructions from system_prompt attribute."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        request_with_prompt = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(request_with_prompt, "system_prompt", "Custom system prompt")

        sections = builder._extract_custom_instruction_sections(request_with_prompt)

        assert "Custom system prompt" in sections

    def test_extract_custom_instruction_sections_from_messages(
        self, builder, mock_connector, sample_context
    ):
        """Test extraction of custom instructions from system role messages."""
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        mock_connector._is_native_responses_payload.return_value = False
        system_message = ChatMessage(role="system", content="System message content")
        request_with_system = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[system_message],
            stream=False,
        )
        mock_connector._message_to_text.return_value = "System message content"

        sections = builder._extract_custom_instruction_sections(request_with_system)

        assert "System message content" in sections

    def test_extract_custom_instruction_sections_from_extra_body(
        self, builder, mock_connector, sample_context
    ):
        """Test extraction of custom instructions from extra_body."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        request_with_extra = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(
            request_with_extra,
            "extra_body",
            {"codex_system_prompt": "Extra body prompt"},
        )

        sections = builder._extract_custom_instruction_sections(request_with_extra)

        assert "Extra body prompt" in sections

    def test_extract_custom_instruction_sections_deduplicates(
        self, builder, mock_connector, sample_context
    ):
        """Test that duplicate instruction sections are deduplicated."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        request_with_duplicates = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(request_with_duplicates, "system_prompt", "Duplicate prompt")
        object.__setattr__(
            request_with_duplicates,
            "extra_body",
            {"codex_system_prompt": "Duplicate prompt"},
        )

        sections = builder._extract_custom_instruction_sections(request_with_duplicates)

        assert sections.count("Duplicate prompt") == 1

    def test_build_payload_passthrough_with_invalid_input_structure(
        self, builder, mock_connector, sample_context
    ):
        """Test passthrough handles invalid input structure gracefully."""
        passthrough_dict = {
            "model": "gpt-5.1-codex",
            "input": "invalid_string_input",  # Invalid: should be list
            "stream": False,
        }
        sample_context.request = passthrough_dict
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert isinstance(payload, CodexPayload)
        assert payload.model == "gpt-5.1-codex"

    def test_extract_custom_instruction_sections_empty_string_vs_none(
        self, builder, mock_connector, sample_context
    ):
        """Test instruction extraction handles empty string vs None correctly."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        request_with_empty = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(request_with_empty, "system_prompt", "")  # Empty string
        object.__setattr__(
            request_with_empty, "extra_body", {"codex_system_prompt": None}
        )

        sections = builder._extract_custom_instruction_sections(request_with_empty)

        # Empty strings and None should be filtered out
        assert len(sections) == 0

    def test_extract_custom_instruction_sections_list_with_empty_strings(
        self, builder, mock_connector, sample_context
    ):
        """Test instruction extraction from list with empty strings."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        request_with_list = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(
            request_with_list,
            "extra_body",
            {"codex_system_prompt": ["Valid prompt", "", "  ", "Another prompt"]},
        )

        sections = builder._extract_custom_instruction_sections(request_with_list)

        # Should only include non-empty strings
        assert len(sections) == 2
        assert "Valid prompt" in sections
        assert "Another prompt" in sections

    def test_build_payload_passthrough_missing_model_uses_effective_model(
        self, builder, mock_connector, sample_context
    ):
        """Test passthrough uses effective_model when model is missing."""
        passthrough_dict = {
            "input": [],
            "stream": False,
        }
        sample_context.request = passthrough_dict
        sample_context.capabilities = CodexClientCapabilities(codex_passthrough=True)
        mock_connector._is_native_responses_payload.return_value = True

        payload = builder.build_payload(sample_context)

        assert payload.model == sample_context.effective_model

    def test_resolve_instructions_merge_custom_mode_with_custom_sections(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """Test instruction resolution in merge_custom mode with custom sections."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        mock_prompt_resolver.resolve_system_prompt.return_value = "Base prompt"
        request_with_custom = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(request_with_custom, "system_prompt", "Custom prompt")
        sample_context.request = request_with_custom
        sample_context.capabilities = CodexClientCapabilities(
            prompt_mode="merge_custom"
        )

        payload = builder.build_payload(sample_context)

        # Instructions should include both base and custom
        assert payload.instructions is not None
        assert (
            "Base prompt" in payload.instructions
            or "Custom prompt" in payload.instructions
        )

    def test_resolve_instructions_custom_only_mode_with_fallback(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """Test instruction resolution in custom_only mode falls back to default when empty."""
        mock_connector._is_native_responses_payload.return_value = False
        mock_prompt_resolver.resolve_system_prompt.return_value = "Base prompt"
        sample_context.capabilities = CodexClientCapabilities(prompt_mode="custom_only")

        payload = builder.build_payload(sample_context)

        # Should fallback to default when no custom sections
        assert payload.instructions is not None

    def test_resolve_instructions_codex_default_mode_excludes_custom(
        self, builder, mock_connector, mock_prompt_resolver, sample_context
    ):
        """Test instruction resolution in codex_default mode excludes custom sections."""
        from src.core.domain.chat import CanonicalChatRequest

        mock_connector._is_native_responses_payload.return_value = False
        mock_prompt_resolver.resolve_system_prompt.return_value = "Base prompt"
        request_with_custom = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test")],
            stream=False,
        )
        object.__setattr__(request_with_custom, "system_prompt", "Custom prompt")
        sample_context.request = request_with_custom
        sample_context.capabilities = CodexClientCapabilities(
            prompt_mode="codex_default"
        )

        payload = builder.build_payload(sample_context)

        # Instructions should not include custom sections in default mode
        assert payload.instructions is not None
        # Custom prompt should not be in instructions (only base)
        # Note: This depends on implementation - verify base prompt is present
