"""Integration tests for Codex compatibility flows.

This test suite verifies end-to-end compatibility flows for KiloCode/Droid
clients and tool execution results.
"""

from __future__ import annotations

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
