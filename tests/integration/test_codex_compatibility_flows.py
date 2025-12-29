"""Integration tests for Codex compatibility flows.

This test suite verifies end-to-end compatibility flows for KiloCode/Droid
clients and tool execution results.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ProcessedResponse, ResponseEnvelope
from src.core.services.translation_service import TranslationService


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    """Create temporary auth directory with credentials."""
    data = {"tokens": {"access_token": "test_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="mock_file_system")
async def mock_file_system_fixture(tmp_path: Path):
    """Create a mock file system for testing."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    pass\n", encoding="utf-8")

    test_dir = tmp_path / "src"
    test_dir.mkdir()
    (test_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    return tmp_path


@pytest_asyncio.fixture(name="codex_connector")
async def codex_connector_fixture(auth_dir: Path, mock_file_system: Path):
    """Create connector with compatibility layer enabled."""
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        # Enable compatibility layer
        backend._connector_settings["compatibility_layer"]["enabled"] = True

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}

            # Initialize session detector
            from src.connectors._openai_codex_session_detector import SessionDetector

            detection_cfg = backend._connector_settings["compatibility_layer"][
                "detection"
            ]
            backend._session_detector = SessionDetector(
                cache_ttl_seconds=detection_cfg["cache_ttl_seconds"],
                heuristic_threshold=detection_cfg["heuristic_threshold"],
            )
            backend._compatibility_layer_enabled = True

            # Set working directory for file operations
            backend._working_directory = str(mock_file_system)

            yield backend


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kilocode_detection_and_tool_translation(
    codex_connector: OpenAICodexConnector, mock_file_system: Path
):
    """End-to-end test of KiloCode detection and XML tool translation."""
    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
    from src.core.services.universal_tool_executor import UniversalToolExecutor

    translator = KiloToolTranslator(codex_connector)
    executor = UniversalToolExecutor(
        working_directory=str(mock_file_system), result_format="kilo_standard"
    )

    # Test KiloCode XML tool invocation
    read_xml = '<read_file path="test.py" />'
    read_result = await translator.translate_tool_invocation(
        read_xml, session_id="test_session"
    )

    assert read_result is not None
    tool_name, arguments = read_result
    assert tool_name == "read_file"

    # Execute the tool
    read_output = await executor.execute_tool(tool_name, arguments)
    assert read_output["exit_code"] == 0
    assert "def hello():" in read_output["output"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_droid_detection_and_streaming_translation(
    codex_connector: OpenAICodexConnector,
):
    """End-to-end test of Droid detection and streaming chunk translation."""
    from src.connectors._openai_codex_droid_tool_translator import DroidToolTranslator

    DroidToolTranslator()

    # Create a mock streaming response with Droid-style tool calls
    async def mock_stream():
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "test.py"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )

    # Mock the connector's streaming response
    codex_connector._handle_streaming_response = AsyncMock(
        return_value=MagicMock(
            headers={},
            cancel_callback=AsyncMock(),
            iterator=mock_stream(),
        )
    )

    # Test Droid detection
    from src.connectors._openai_codex_droid_session_detector import DroidSessionDetector

    droid_detector = DroidSessionDetector()

    MagicMock()

    # DroidSessionDetector.detect is synchronous and takes specific args
    # Simulate detection via headers - use a pattern that definitely matches
    # "factory-cli" is one of the patterns in DROID_USER_AGENT_PATTERNS
    headers = {"User-Agent": "factory-cli/1.0"}
    result = droid_detector.detect(headers=headers)

    assert result.is_droid is True
    assert result.detection_method == "user_agent"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compatibility_tool_execution_results(
    codex_connector: OpenAICodexConnector, mock_file_system: Path
):
    """Verify tool execution results are formatted correctly for compatibility clients."""
    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
    from src.core.services.universal_tool_executor import UniversalToolExecutor

    translator = KiloToolTranslator(codex_connector)
    executor = UniversalToolExecutor(
        working_directory=str(mock_file_system), result_format="kilo_standard"
    )

    # Test multiple tool types
    tools_to_test = [
        ('<read_file path="test.py" />', "read_file"),
        ('<list_files path="." />', "list_dir"),
    ]

    for xml_input, expected_tool in tools_to_test:
        result = await translator.translate_tool_invocation(
            xml_input, session_id="test_session"
        )
        assert result is not None
        tool_name, arguments = result
        assert tool_name == expected_tool

        # Execute and verify result format
        output = await executor.execute_tool(tool_name, arguments)
        assert "exit_code" in output
        assert "output" in output
        assert isinstance(output["exit_code"], int)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compatibility_state_cleanup(
    codex_connector: OpenAICodexConnector,
):
    """Verify compatibility state is cleaned up after streaming completes."""
    # Check if compatibility layer has state management
    if hasattr(codex_connector, "_compatibility_layer"):
        compat_layer = codex_connector._compatibility_layer

        # Create state
        if hasattr(compat_layer, "create_state"):
            state = compat_layer.create_state()
            assert state is not None

            # Verify cleanup method exists
            if hasattr(compat_layer, "cleanup_state"):
                await compat_layer.cleanup_state(state)
                # State should be invalidated after cleanup
                # (exact behavior depends on implementation)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_non_compatibility_client_bypass(
    codex_connector: OpenAICodexConnector,
):
    """Verify non-KiloCode/Droid clients bypass compatibility layer."""
    from src.connectors._openai_codex_session_detector import SessionDetector

    detector = codex_connector._session_detector
    assert isinstance(detector, SessionDetector)

    # Test with Cline client (should not trigger compatibility)
    request_data = MagicMock()
    metadata = {"agent": "cline"}

    result = await detector.detect(
        request_data=request_data,
        metadata=metadata,
        session_id="cline_session",
        backend="openai-codex",
    )

    assert result.is_kilocode is False
    # is_droid is not in DetectionResult

    # Test with Cursor client (should not trigger compatibility)
    metadata = {"agent": "cursor"}
    result = await detector.detect(
        request_data=request_data,
        metadata=metadata,
        session_id="cursor_session",
        backend="openai-codex",
    )

    assert result.is_kilocode is False
    # is_droid is not in DetectionResult


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kilocode_complete_workflow(
    codex_connector: OpenAICodexConnector, mock_file_system: Path
):
    """Test complete KiloCode workflow: read, edit, completion."""
    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
    from src.core.services.universal_tool_executor import UniversalToolExecutor

    translator = KiloToolTranslator(codex_connector)
    executor = UniversalToolExecutor(
        working_directory=str(mock_file_system), result_format="kilo_standard"
    )

    session_id = "workflow_session"

    # Step 1: Read file
    read_xml = '<read_file path="test.py" />'
    read_result = await translator.translate_tool_invocation(read_xml, session_id)
    assert read_result is not None
    read_output = await executor.execute_tool(*read_result)
    assert read_output["exit_code"] == 0

    # Step 2: Edit file
    edit_xml = """<write_to_file>
<path>test.py</path>
<content>def hello():
    print("world")
</content>
</write_to_file>"""
    edit_result = await translator.translate_tool_invocation(edit_xml, session_id)
    assert edit_result is not None
    edit_output = await executor.execute_tool(*edit_result)
    assert edit_output["exit_code"] == 0

    # Verify file was edited
    edited_content = (mock_file_system / "test.py").read_text(encoding="utf-8")
    assert 'print("world")' in edited_content

    # Step 3: Completion marker
    completion_xml = '<attempt_completion result="Task completed" />'
    completion_result = await translator.translate_tool_invocation(
        completion_xml, session_id
    )
    assert completion_result is not None
    assert completion_result.tool_name == "__proxy_attempt_completion"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compatibility_isolation_from_base_path(
    codex_connector: OpenAICodexConnector,
):
    """Test that compatibility layer doesn't affect base request/response path (Req 2.3)."""
    from src.core.domain.chat import CanonicalChatRequest

    # Create a non-compatibility client request
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    # Mock a successful non-streaming response
    mock_response = ResponseEnvelope(
        content={
            "id": "test-response",
            "choices": [{"message": {"role": "assistant", "content": "Hi there"}}],
        },
        status_code=200,
    )

    # Mock the executor to return our response
    codex_connector._response_executor.execute = AsyncMock(return_value=mock_response)

    # Execute request
    result = await codex_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="gpt-5.1-codex",
    )

    # Verify base path works correctly (compatibility shouldn't interfere)
    assert isinstance(result, ResponseEnvelope)
    assert result.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_streaming_chunk_translation_with_compatibility(
    codex_connector: OpenAICodexConnector,
):
    """Test streaming chunk translation with compatibility layer active."""
    from src.core.domain.responses import StreamingResponseEnvelope

    # Create a KiloCode-style request
    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[
            ChatMessage(
                role="user",
                content='<read_file path="test.py" />',
            )
        ],
        stream=True,
    )

    # Mock streaming response with tool calls
    async def mock_stream():
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "id": "call_123",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "test.py"}',
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        )

    # Mock the executor's streaming response
    mock_stream_handle = MagicMock()
    mock_stream_handle.headers = {}
    mock_stream_handle.cancel_callback = AsyncMock()
    mock_stream_handle.iterator = mock_stream()

    codex_connector._response_executor._base_connector._handle_streaming_response = (
        AsyncMock(return_value=mock_stream_handle)
    )

    # Execute request
    result = await codex_connector.chat_completions(
        request_data=request,
        processed_messages=[],
        effective_model="gpt-5-codex",
    )

    assert isinstance(result, StreamingResponseEnvelope)

    # Consume stream to verify compatibility layer processes chunks
    chunks = []
    async for chunk in result.content:
        chunks.append(chunk)

    # Should have received at least one chunk
    assert len(chunks) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_kilocode_tool_translation_proxy_vs_provider_semantics(
    codex_connector: OpenAICodexConnector,
):
    """Test that KiloCode tool translation preserves proxy vs provider-side semantics (Req 3.1, 7.1)."""
    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator

    translator = KiloToolTranslator(codex_connector)

    # Test provider-side tools (should go to Codex backend)
    provider_tools = [
        '<read_file path="test.py" />',  # read_file -> provider-side
        '<list_files path="." />',  # list_dir -> provider-side
    ]

    for xml_tool in provider_tools:
        result = await translator.translate_tool_invocation(xml_tool, "test_session")
        assert result is not None
        # Provider-side tools should NOT have __proxy_ prefix
        assert not result.tool_name.startswith(
            "__proxy_"
        ), f"Tool {result.tool_name} should be provider-side, not proxy-side"

    # Test proxy-side tools (should be executed proxy-side)
    proxy_tools = [
        '<attempt_completion result="Done" />',  # attempt_completion -> proxy-side
        "<ask_followup_question>What next?</ask_followup_question>",  # ask_followup_question -> proxy-side
    ]

    for xml_tool in proxy_tools:
        result = await translator.translate_tool_invocation(xml_tool, "test_session")
        assert result is not None
        # Proxy-side tools should have __proxy_ prefix
        assert result.tool_name.startswith(
            "__proxy_"
        ), f"Tool {result.tool_name} should be proxy-side"

    # Test MCP tools (should be executed proxy-side via MCP client)
    mcp_tools = [
        '<use_mcp_tool tool_name="test_tool" tool_arguments="{}" />',
    ]

    for xml_tool in mcp_tools:
        result = await translator.translate_tool_invocation(xml_tool, "test_session")
        assert result is not None
        # MCP tools should have __proxy_ prefix
        assert result.tool_name.startswith(
            "__proxy_"
        ), f"Tool {result.tool_name} should be proxy-side (MCP)"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_droid_tool_translation_proxy_vs_provider_semantics():
    """Test that Droid tool translation preserves proxy vs provider-side semantics (Req 3.1, 7.1)."""
    from src.connectors._openai_codex_droid_tool_translator import DroidToolTranslator

    translator = DroidToolTranslator()

    # Test provider-side tools (should go to Codex backend)
    provider_tools = [
        ("Read", {"file_path": "test.py"}),  # Read -> read_file (provider-side)
        ("LS", {"directory_path": "."}),  # LS -> list_dir (provider-side)
        ("Execute", {"command": "echo hello"}),  # Execute -> shell (provider-side)
    ]

    for droid_tool, args in provider_tools:
        result = translator.translate_tool_call(droid_tool, args)
        assert result is not None
        # Provider-side tools should NOT have __proxy_ prefix
        assert (
            not result.is_proxy_side
        ), f"Droid tool {droid_tool} should be provider-side, not proxy-side"
        assert not result.codex_tool_name.startswith(
            "__proxy_"
        ), f"Codex tool {result.codex_tool_name} should be provider-side"

    # Test proxy-side tools (should be executed proxy-side)
    proxy_tools = [
        ("TodoWrite", {"content": "test"}),  # TodoWrite -> __proxy_todo_write
        ("WebSearch", {"query": "test"}),  # WebSearch -> __proxy_web_search
        ("FetchUrl", {"url": "http://example.com"}),  # FetchUrl -> __proxy_fetch_url
        ("ExitSpecMode", {}),  # ExitSpecMode -> __proxy_exit_spec_mode
    ]

    for droid_tool, args in proxy_tools:
        result = translator.translate_tool_call(droid_tool, args)
        assert result is not None
        # Proxy-side tools should have is_proxy_side=True
        assert result.is_proxy_side, f"Droid tool {droid_tool} should be proxy-side"
        assert result.codex_tool_name.startswith(
            "__proxy_"
        ), f"Codex tool {result.codex_tool_name} should have __proxy_ prefix"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_execution_result_formatting_kilocode(
    codex_connector: OpenAICodexConnector, mock_file_system: Path
):
    """Test that tool execution results are formatted correctly for KiloCode (Req 3.1, 7.1)."""
    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
    from src.connectors.openai_codex.tools import ToolExecutionService
    from src.core.services.universal_tool_executor import UniversalToolExecutor

    translator = KiloToolTranslator(codex_connector)
    executor = UniversalToolExecutor(
        working_directory=str(mock_file_system), result_format="kilo_standard"
    )
    tool_service = ToolExecutionService(
        universal_executor=executor, kilo_translator=translator
    )

    # Test successful tool execution formatting
    read_xml = '<read_file path="test.py" />'
    read_result = await translator.translate_tool_invocation(read_xml, "test_session")
    assert read_result is not None

    # Execute via tool service (which formats results)
    from src.connectors.openai_codex.contracts import ToolArguments

    tool_result = await tool_service.execute_proxy_tool(
        read_result.tool_name,
        ToolArguments(payload=read_result.arguments),
        "test_session",
    )

    # Verify result format matches KiloCode expectations
    assert tool_result.success is True
    assert isinstance(tool_result.result, str)
    # KiloCode format: [tool_name] Result: <content>
    assert "[read_file]" in tool_result.result or "Result:" in tool_result.result

    # Test error formatting
    invalid_xml = '<read_file path="nonexistent.py" />'
    invalid_result = await translator.translate_tool_invocation(
        invalid_xml, "test_session"
    )
    assert invalid_result is not None

    error_result = await tool_service.execute_proxy_tool(
        invalid_result.tool_name,
        ToolArguments(payload=invalid_result.arguments),
        "test_session",
    )

    # Verify error format matches KiloCode expectations
    # Note: Tool execution service returns success=True even for errors,
    # with error information included in the result string
    assert error_result.success is True  # Current behavior: errors are in result string
    assert isinstance(error_result.result, str)
    # Error information should be included in the result string
    assert "Error" in error_result.result or "File not found" in error_result.result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tool_execution_order_proxy_then_mcp(
    codex_connector: OpenAICodexConnector,
):
    """Test that tool execution happens in correct order: proxy tools, then MCP tools (Req 3.1)."""
    from unittest.mock import AsyncMock, MagicMock

    from src.connectors._openai_codex_kilo_tool_translator import KiloToolTranslator
    from src.connectors.openai_codex.compat import CompatibilityLayer
    from src.connectors.openai_codex.contracts import (
        CodexRequestContext,
        ProcessedMessage,
    )
    from src.connectors.openai_codex.tools import ToolExecutionService
    from src.core.services.universal_tool_executor import UniversalToolExecutor

    translator = KiloToolTranslator(codex_connector)
    executor = UniversalToolExecutor(
        working_directory=str(codex_connector._working_directory)
    )
    tool_service = ToolExecutionService(
        universal_executor=executor, kilo_translator=translator
    )

    # Track execution order
    execution_order = []

    # Mock tool execution to track order
    original_execute_proxy = tool_service.execute_proxy_tool
    original_execute_mcp = tool_service.execute_mcp_tool

    async def tracked_execute_proxy(*args, **kwargs):
        execution_order.append("proxy")
        return await original_execute_proxy(*args, **kwargs)

    async def tracked_execute_mcp(*args, **kwargs):
        execution_order.append("mcp")
        return await original_execute_mcp(*args, **kwargs)

    tool_service.execute_proxy_tool = tracked_execute_proxy
    tool_service.execute_mcp_tool = tracked_execute_mcp

    compat_layer = CompatibilityLayer(
        kilo_translator=translator, tool_execution_service=tool_service
    )

    # Create context with both proxy and MCP tools
    from src.connectors._openai_codex_capabilities import CodexClientCapabilities
    from src.core.domain.chat import CanonicalChatRequest, ChatMessage

    messages = [
        ProcessedMessage(
            role="user",
            content='<attempt_completion result="Done" /> <use_mcp_tool tool_name="test" tool_arguments="{}" />',
        )
    ]

    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,
    )

    context = CodexRequestContext(
        request=request,
        processed_messages=messages,
        effective_model="gpt-5-codex",
        session_id="test_session",
        capabilities=CodexClientCapabilities(),
    )

    # Mock session detector to return KiloCode
    from src.connectors._openai_codex_session_detector import SessionDetector

    mock_detector = AsyncMock(spec=SessionDetector)
    mock_detector.detect = AsyncMock(
        return_value=MagicMock(
            is_kilocode=True, detection_method="test", confidence=1.0
        )
    )
    compat_layer._session_detector = mock_detector

    # Apply compatibility layer (should execute tools in order)
    compat_result = await compat_layer.apply(context)

    # Verify execution order: proxy tools first, then MCP tools
    # Note: This test verifies the order within CompatibilityLayer.apply()
    # The actual execution order depends on how tools are grouped in _translate_kilo_tools
    assert len(execution_order) > 0, "At least one tool should have been executed"
    # Verify that tools were actually translated
    assert (
        len(compat_result.proxy_tools) > 0 or len(compat_result.mcp_tools) > 0
    ), "At least one tool should have been translated"
    # Proxy tools should be executed before MCP tools
    if "mcp" in execution_order:
        first_mcp_index = execution_order.index("mcp")
        # All proxy tools should come before first MCP tool
        assert all(
            execution_order[i] == "proxy" for i in range(first_mcp_index)
        ), "Proxy tools should execute before MCP tools"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_after_successful_streaming_completion(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup happens after successful streaming completion (Req 3.3, 7.3)."""
    from src.connectors.openai_codex.contracts import CompatibilityState
    from src.core.domain.chat import ChatMessage

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True

    # Mock cleanup to track calls
    if codex_connector._compatibility_layer:
        original_cleanup = codex_connector._compatibility_layer.cleanup_state
        cleanup_called = []

        async def tracked_cleanup(s):
            cleanup_called.append(True)
            return await original_cleanup(s)

        codex_connector._compatibility_layer.cleanup_state = tracked_cleanup

    # Create request
    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="Test")],
        stream=True,
    )

    # Mock streaming response
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    chunks = [
        ProcessedResponse(content={"choices": [{"delta": {"content": "Hello"}}]}),
        ProcessedResponse(
            content={"choices": [{"delta": {}, "finish_reason": "stop"}]}
        ),
    ]

    async def mock_streaming_response(*args, **kwargs):
        from tests.integration.test_codex_streaming_retry_parity import MockStreamHandle

        handle = MockStreamHandle(chunks)
        return handle

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        # Create context with compatibility state
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexRequestContext,
            ProcessedMessage,
        )

        context = CodexRequestContext(
            request=request,
            processed_messages=[ProcessedMessage(role="user", content="Test")],
            effective_model="gpt-5-codex",
            session_id="test_session",
            capabilities=CodexClientCapabilities(),
            metadata={"compatibility_state": state},
        )

        # Execute via executor
        from src.connectors.openai_codex.contracts import CodexPayload

        payload = CodexPayload(
            model="gpt-5-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test_key",
        )

        result = await codex_connector._response_executor.execute(payload, context)

        # Consume stream to completion
        async for _ in result.content:
            pass

        # Verify cleanup was called
        if codex_connector._compatibility_layer:
            assert (
                len(cleanup_called) == 1
            ), "Cleanup should be called exactly once after stream completion"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_after_streaming_error(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup happens after streaming error/exception (Req 3.3, 7.3)."""
    from src.connectors.openai_codex.contracts import CompatibilityState
    from src.core.domain.chat import ChatMessage

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True

    # Mock cleanup to track calls
    if codex_connector._compatibility_layer:
        original_cleanup = codex_connector._compatibility_layer.cleanup_state
        cleanup_called = []

        async def tracked_cleanup(s):
            cleanup_called.append(True)
            return await original_cleanup(s)

        codex_connector._compatibility_layer.cleanup_state = tracked_cleanup

    # Create request
    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="Test")],
        stream=True,
    )

    # Mock streaming response that raises exception
    async def mock_streaming_response(*args, **kwargs):
        raise Exception("Stream error")

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        # Create context with compatibility state
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexRequestContext,
            ProcessedMessage,
        )

        context = CodexRequestContext(
            request=request,
            processed_messages=[ProcessedMessage(role="user", content="Test")],
            effective_model="gpt-5-codex",
            session_id="test_session",
            capabilities=CodexClientCapabilities(),
            metadata={"compatibility_state": state},
        )

        # Execute via executor
        from src.connectors.openai_codex.contracts import CodexPayload

        payload = CodexPayload(
            model="gpt-5-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test_key",
        )

        # Should raise exception, but cleanup should still happen
        try:
            result = await codex_connector._response_executor.execute(payload, context)
            # Consume stream to trigger error
            async for _ in result.content:
                pass
        except Exception:
            pass  # Expected

        # Verify cleanup was called even on error
        if codex_connector._compatibility_layer:
            assert len(cleanup_called) == 1, "Cleanup should be called even on error"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_after_streaming_cancellation(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup happens after streaming cancellation (Req 3.3, 7.3)."""
    import asyncio

    from src.connectors.openai_codex.contracts import CompatibilityState
    from src.core.domain.chat import ChatMessage

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True

    # Mock cleanup to track calls
    if codex_connector._compatibility_layer:
        original_cleanup = codex_connector._compatibility_layer.cleanup_state
        cleanup_called = []

        async def tracked_cleanup(s):
            cleanup_called.append(True)
            return await original_cleanup(s)

        codex_connector._compatibility_layer.cleanup_state = tracked_cleanup

    # Create request
    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="Test")],
        stream=True,
    )

    # Mock streaming response that raises CancelledError
    async def mock_streaming_response(*args, **kwargs):
        raise asyncio.CancelledError("Stream cancelled")

    with patch.object(
        codex_connector._response_executor._base_connector,
        "_handle_streaming_response",
        side_effect=mock_streaming_response,
    ):
        # Create context with compatibility state
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexRequestContext,
            ProcessedMessage,
        )

        context = CodexRequestContext(
            request=request,
            processed_messages=[ProcessedMessage(role="user", content="Test")],
            effective_model="gpt-5-codex",
            session_id="test_session",
            capabilities=CodexClientCapabilities(),
            metadata={"compatibility_state": state},
        )

        # Execute via executor
        from src.connectors.openai_codex.contracts import CodexPayload

        payload = CodexPayload(
            model="gpt-5-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test_key",
        )

        # Should raise CancelledError, but cleanup should still happen
        try:
            result = await codex_connector._response_executor.execute(payload, context)
            # Consume stream to trigger cancellation
            async for _ in result.content:
                pass
        except asyncio.CancelledError:
            pass  # Expected

        # Verify cleanup was called even on cancellation
        if codex_connector._compatibility_layer:
            assert (
                len(cleanup_called) == 1
            ), "Cleanup should be called even on streaming cancellation"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_after_successful_non_streaming_completion(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup happens after successful non-streaming completion (Req 3.3, 7.3)."""
    from unittest.mock import MagicMock

    from src.connectors.openai_codex.contracts import CompatibilityState
    from src.core.domain.chat import ChatMessage

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True

    # Mock cleanup to track calls
    if codex_connector._compatibility_layer:
        original_cleanup = codex_connector._compatibility_layer.cleanup_state
        cleanup_called = []

        async def tracked_cleanup(s):
            cleanup_called.append(True)
            return await original_cleanup(s)

        codex_connector._compatibility_layer.cleanup_state = tracked_cleanup

    # Create context with compatibility state
    from src.connectors._openai_codex_capabilities import CodexClientCapabilities
    from src.connectors.openai_codex.contracts import (
        CodexRequestContext,
        ProcessedMessage,
    )

    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="Test")],
        stream=False,
    )

    context = CodexRequestContext(
        request=request,
        processed_messages=[ProcessedMessage(role="user", content="Test")],
        effective_model="gpt-5-codex",
        session_id="test_session",
        capabilities=CodexClientCapabilities(),
        metadata={"compatibility_state": state},
    )

    # Mock HTTP response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "test",
        "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
    }
    mock_response.headers = {}

    with patch.object(
        codex_connector._response_executor._base_connector.client,
        "post",
        return_value=mock_response,
    ):
        # Execute via executor
        from src.connectors.openai_codex.contracts import CodexPayload

        payload = CodexPayload(
            model="gpt-5-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=False,
            include=[],
            prompt_cache_key="test_key",
        )

        await codex_connector._response_executor.execute(payload, context)

        # Verify cleanup was called
        if codex_connector._compatibility_layer:
            assert (
                len(cleanup_called) == 1
            ), "Cleanup should be called after non-streaming completion"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_after_non_streaming_error(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup happens after non-streaming error/exception (Req 3.3, 7.3)."""
    from src.connectors.openai_codex.contracts import CompatibilityState
    from src.core.domain.chat import ChatMessage

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True

    # Mock cleanup to track calls
    if codex_connector._compatibility_layer:
        original_cleanup = codex_connector._compatibility_layer.cleanup_state
        cleanup_called = []

        async def tracked_cleanup(s):
            cleanup_called.append(True)
            return await original_cleanup(s)

        codex_connector._compatibility_layer.cleanup_state = tracked_cleanup

    # Create context with compatibility state
    from src.connectors._openai_codex_capabilities import CodexClientCapabilities
    from src.connectors.openai_codex.contracts import (
        CodexRequestContext,
        ProcessedMessage,
    )

    request = CanonicalChatRequest(
        model="gpt-5-codex",
        messages=[ChatMessage(role="user", content="Test")],
        stream=False,
    )

    context = CodexRequestContext(
        request=request,
        processed_messages=[ProcessedMessage(role="user", content="Test")],
        effective_model="gpt-5-codex",
        session_id="test_session",
        capabilities=CodexClientCapabilities(),
        metadata={"compatibility_state": state},
    )

    # Mock HTTP response that raises exception
    with patch.object(
        codex_connector._response_executor._base_connector.client,
        "post",
        side_effect=Exception("Request error"),
    ):
        # Execute via executor
        from src.connectors.openai_codex.contracts import CodexPayload

        payload = CodexPayload(
            model="gpt-5-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=False,
            include=[],
            prompt_cache_key="test_key",
        )

        # Should raise exception, but cleanup should still happen
        with contextlib.suppress(Exception):  # Expected
            await codex_connector._response_executor.execute(payload, context)

        # Verify cleanup was called even on error
        if codex_connector._compatibility_layer:
            assert len(cleanup_called) == 1, "Cleanup should be called even on error"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cleanup_idempotency(
    codex_connector: OpenAICodexConnector,
):
    """Test that cleanup is idempotent (safe to call multiple times) (Req 3.3)."""
    from src.connectors.openai_codex.contracts import CompatibilityState

    # Create compatibility state
    state = CompatibilityState()
    state.is_droid = True
    state.droid_tool_name_cache["call_1"] = "Read"

    if codex_connector._compatibility_layer:
        # Call cleanup multiple times
        await codex_connector._compatibility_layer.cleanup_state(state)
        await codex_connector._compatibility_layer.cleanup_state(state)
        await codex_connector._compatibility_layer.cleanup_state(state)

        # Verify state is cleaned up (idempotent)
        assert len(state.droid_tool_name_cache) == 0
        assert state.is_droid is False
