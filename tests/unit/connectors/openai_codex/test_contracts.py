"""Tests for OpenAI Codex connector contract models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexConnectorDependencies,
    CodexConnectorSettings,
    CodexInitOptions,
    CodexInputItem,
    CodexPayload,
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityResult,
    CompatibilityState,
    MessagePart,
    PendingToolCall,
    ProcessedMessage,
    ProviderStreamChunk,
    ReasoningSpec,
    ToolArguments,
    ToolExecutionResult,
)
from src.core.domain.chat import CanonicalChatRequest


class TestProcessedMessage:
    """Tests for ProcessedMessage contract."""

    def test_create_with_text_content(self):
        """Test creating ProcessedMessage with text content."""
        msg = ProcessedMessage(
            role="user",
            content="Hello, world!",
        )
        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.tool_calls is None
        assert msg.name is None
        assert msg.tool_call_id is None
        assert msg.metadata is None

    def test_create_with_multimodal_content(self):
        """Test creating ProcessedMessage with multimodal content."""
        parts = [
            MessagePart(type="text", text="Hello"),
            MessagePart(type="text", text="World"),
        ]
        msg = ProcessedMessage(
            role="user",
            content=parts,
        )
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2

    def test_create_with_tool_calls(self):
        """Test creating ProcessedMessage with tool calls."""
        from src.core.domain.chat import FunctionCall, ToolCall

        tool_call = ToolCall(
            id="call_123",
            type="function",
            function=FunctionCall(name="read_file", arguments='{"path": "test.py"}'),
        )
        msg = ProcessedMessage(
            role="assistant",
            content="I'll read the file.",
            tool_calls=[tool_call],
        )
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1


class TestOpenAICodexNormalizeProcessedMessages:
    """Regression: ChatMessage / dict payloads must coerce missing content for ProcessedMessage."""

    def test_defaults_missing_content_for_codex_bash_style_user(self):
        from src.connectors._openai_codex_connector import OpenAICodexConnector
        from src.core.domain.chat import ChatMessage

        inst = OpenAICodexConnector.__new__(OpenAICodexConnector)
        object.__setattr__(inst, "_file_observer_ref", None)

        raw_dict = {"role": "user", "name": "bash"}
        out_dict = OpenAICodexConnector._normalize_processed_messages(inst, [raw_dict])
        assert len(out_dict) == 1
        assert out_dict[0].content == ""

        cm = ChatMessage(role="user", name="bash", content=None)
        dumped = cm.model_dump(exclude_none=True)
        out_cm = OpenAICodexConnector._normalize_processed_messages(inst, [dumped])
        assert len(out_cm) == 1
        assert out_cm[0].content == ""


class TestCodexRequestContext:
    """Tests for CodexRequestContext contract."""

    def test_create_valid_context(self):
        """Test creating a valid CodexRequestContext."""
        from src.core.domain.chat import ChatMessage

        request = CanonicalChatRequest(
            model="openai-codex:gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        capabilities = CodexClientCapabilities()
        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            effective_model="gpt-5.1-codex",
            capabilities=capabilities,
            session_id="test-session-123",
        )
        assert context.session_id == "test-session-123"
        assert context.effective_model == "gpt-5.1-codex"
        assert context.metadata is None

    def test_effective_model_must_be_stripped(self):
        """Test that effective_model should be stripped of vendor prefix."""
        from src.core.domain.chat import ChatMessage

        request = CanonicalChatRequest(
            model="openai-codex:gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        capabilities = CodexClientCapabilities()
        # This should pass - effective_model is already stripped
        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            effective_model="gpt-5.1-codex",  # Already stripped
            capabilities=capabilities,
            session_id="test-session",
        )
        assert context.effective_model == "gpt-5.1-codex"

    def test_session_id_required(self):
        """Test that session_id is required."""
        from src.core.domain.chat import ChatMessage

        request = CanonicalChatRequest(
            model="openai-codex:gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        capabilities = CodexClientCapabilities()
        with pytest.raises(ValidationError):
            CodexRequestContext(
                request=request,
                processed_messages=[],
                effective_model="gpt-5.1-codex",
                capabilities=capabilities,
                session_id="",  # Empty string should fail
            )


class TestCodexPayload:
    """Tests for CodexPayload contract."""

    def test_create_minimal_payload(self):
        """Test creating a minimal CodexPayload."""
        payload = CodexPayload(
            model="gpt-5.1-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=False,
            include=[],
            prompt_cache_key="",
        )
        assert payload.model == "gpt-5.1-codex"
        assert payload.input == []
        assert payload.reasoning is None
        assert payload.instructions is None

    def test_create_with_reasoning(self):
        """Test creating CodexPayload with reasoning spec."""
        reasoning = ReasoningSpec(effort="high", summary="auto")
        payload = CodexPayload(
            model="gpt-5.1-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=False,
            include=[],
            prompt_cache_key="",
            reasoning=reasoning,
        )
        assert payload.reasoning is not None
        assert payload.reasoning.effort == "high"


class TestCompatibilityState:
    """Tests for CompatibilityState contract."""

    def test_create_state(self):
        """Test creating CompatibilityState."""
        state = CompatibilityState(
            is_kilocode=False,
            is_droid=False,
        )
        assert state.is_kilocode is False
        assert state.is_droid is False
        assert state.droid_tool_name_cache == {}
        assert state.droid_tool_args_buffer == {}
        assert state.pending_tool_calls == []

    def test_state_is_per_request(self):
        """Test that CompatibilityState is designed for per-request use."""
        state1 = CompatibilityState(
            is_kilocode=True,
            is_droid=False,
        )
        state2 = CompatibilityState(
            is_kilocode=False,
            is_droid=True,
        )
        # States should be independent
        assert state1.is_kilocode is True
        assert state2.is_droid is True


class TestCompatibilityResult:
    """Tests for CompatibilityResult contract."""

    def test_create_result(self):
        """Test creating CompatibilityResult."""
        state = CompatibilityState(
            is_kilocode=False,
            is_droid=False,
        )
        result = CompatibilityResult(
            codex_tools=[],
            proxy_tools=[],
            mcp_tools=[],
            tool_results=[],
            state=state,
        )
        assert result.codex_tools == []
        assert result.state == state


class TestCodexInitOptions:
    """Tests for CodexInitOptions contract."""

    def test_create_with_all_options(self):
        """Test creating CodexInitOptions with all options."""
        options = CodexInitOptions(
            openai_codex_path="/path/to/auth.json",
            openai_api_base_url="https://api.example.com/v1",
            backend_extras={"key": "value"},
        )
        assert options.openai_codex_path == "/path/to/auth.json"
        assert options.openai_api_base_url == "https://api.example.com/v1"

    def test_create_with_none_options(self):
        """Test creating CodexInitOptions with None values."""
        options = CodexInitOptions()
        assert options.openai_codex_path is None
        assert options.openai_api_base_url is None
        assert options.backend_extras is None


class TestCodexConnectorSettings:
    """Tests for CodexConnectorSettings contract."""

    def test_create_settings(self):
        """Test creating CodexConnectorSettings."""
        capabilities = CodexClientCapabilities()
        settings = CodexConnectorSettings(
            default_capabilities=capabilities,
            agent_overrides={},
            prompt={
                "template": None,
                "prepend": [],
                "append": [],
                "deduplicate": True,
                "fallback_to_default": True,
            },
            tool_schema={
                "base_tools": None,
                "custom_tools": [],
            },
            streaming={
                "max_retries": 2,
                "retry_backoff_seconds": (0.5, 1.5, 3.0),
            },
            compatibility_layer={
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
            renderer={
                "aliases": {},
                "modules": {},
                "default": "none",
                "fallback": "summary",
            },
        )
        assert settings.default_capabilities == capabilities
        assert settings.agent_overrides == {}


class TestSupportingStructures:
    """Tests for supporting contract structures."""

    def test_message_part(self):
        """Test MessagePart structure."""
        part = MessagePart(type="text", text="Hello")
        assert part.type == "text"
        assert part.text == "Hello"
        assert part.data is None

    def test_codex_input_item(self):
        """Test CodexInputItem structure."""
        item = CodexInputItem(type="user", content="Hello")
        assert item.type == "user"
        assert item.content == "Hello"

    def test_codex_tool_schema(self):
        """Test CodexToolSchema structure."""
        schema = CodexToolSchema(
            name="read_file",
            description="Read a file",
            parameters={"type": "object"},
            type="function",
        )
        assert schema.name == "read_file"
        assert schema.type == "function"

    def test_tool_arguments(self):
        """Test ToolArguments structure."""
        args = ToolArguments(payload={"path": "test.py"})
        assert args.payload == {"path": "test.py"}

    def test_tool_execution_result(self):
        """Test ToolExecutionResult structure."""
        result = ToolExecutionResult(
            success=True,
            result="File contents",
            error=None,
            metadata=None,
        )
        assert result.success is True
        assert result.result == "File contents"
        assert result.error is None

    def test_provider_stream_chunk(self):
        """Test ProviderStreamChunk structure."""
        chunk_data = {"type": "delta", "content": "Hello"}
        chunk = ProviderStreamChunk(raw=chunk_data)
        assert chunk.raw == chunk_data

    def test_pending_tool_call(self):
        """Test PendingToolCall structure."""
        pending = PendingToolCall(
            id="call_123",
            name="read_file",
            command_text="read_file test.py",
        )
        assert pending.id == "call_123"
        assert pending.name == "read_file"

    def test_reasoning_spec(self):
        """Test ReasoningSpec structure."""
        spec = ReasoningSpec(effort="medium", summary="auto")
        assert spec.effort == "medium"
        assert spec.summary == "auto"


class TestCodexConnectorDependencies:
    """Tests for CodexConnectorDependencies bundle."""

    def test_create_with_all_none(self):
        """Test creating CodexConnectorDependencies with all None."""
        deps = CodexConnectorDependencies()
        assert deps.settings_loader is None
        assert deps.credential_manager is None
        assert deps.payload_builder is None
        assert deps.response_executor is None
        assert deps.compatibility_layer is None
        assert deps.tool_execution_service is None
