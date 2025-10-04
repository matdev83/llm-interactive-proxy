"""Unit tests for gemini-cli-acp backend connector."""

import asyncio
import contextlib
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.core.common.exceptions import (
    APITimeoutError,
    BackendError,
    ConfigurationError,
    ServiceUnavailableError,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def connector(mock_client):
    """Create a fresh connector instance for each test."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    translation_service = TranslationService()
    return GeminiCliAcpConnector(mock_client, config, translation_service)


class TestGeminiCliAcpConnectorInitialization:
    """Test connector initialization."""

    async def test_initialize_with_project_dir(self, connector, temp_workspace):
        """Test initialization with explicit project directory."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

            assert connector.is_functional is True
            assert connector._project_dir == temp_workspace.resolve()

    async def test_initialize_with_environment_variable(
        self, connector, temp_workspace
    ):
        """Test initialization with project directory from environment variable."""
        with (
            patch.dict("os.environ", {"GEMINI_CLI_WORKSPACE": str(temp_workspace)}),
            patch.object(connector, "_check_gemini_cli_available", return_value=True),
        ):
            await connector.initialize()

            assert connector.is_functional is True
            assert connector._project_dir == temp_workspace.resolve()

    async def test_initialize_with_current_directory(self, connector):
        """Test initialization falls back to current directory."""
        with (
            patch("os.getcwd", return_value="/fake/cwd"),
            patch("pathlib.Path.exists", return_value=True),
            patch.object(connector, "_check_gemini_cli_available", return_value=True),
        ):
            await connector.initialize()

            assert connector.is_functional is True
            assert str(connector._project_dir).endswith("cwd")

    async def test_initialize_gemini_cli_not_found(self, connector, temp_workspace):
        """Test initialization fails when gemini-cli not found."""
        with (
            patch.object(connector, "_check_gemini_cli_available", return_value=False),
            pytest.raises(ConfigurationError) as exc_info,
        ):
            await connector.initialize(project_dir=str(temp_workspace))

        assert "gemini-cli executable not found" in str(exc_info.value)
        assert connector.is_functional is False

    async def test_initialize_with_custom_executable(self, connector, temp_workspace):
        """Test initialization with custom gemini-cli executable path."""
        custom_path = "/usr/local/bin/gemini"
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(
                project_dir=str(temp_workspace), gemini_cli_executable=custom_path
            )

            assert connector._gemini_cli_executable == custom_path

    async def test_initialize_with_custom_model(self, connector, temp_workspace):
        """Test initialization with custom model."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(
                project_dir=str(temp_workspace), model="gemini-2.5-pro"
            )

            assert connector._model == "gemini-2.5-pro"

    async def test_initialize_with_auto_accept_false(self, connector, temp_workspace):
        """Test initialization with auto_accept disabled."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(
                project_dir=str(temp_workspace), auto_accept=False
            )

            assert connector._auto_accept is False


class TestGeminiCliAcpConnectorProcessManagement:
    """Test process lifecycle management."""

    async def test_spawn_process_success(self, connector, temp_workspace):
        """Test spawning gemini-cli process successfully."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.stdin = MagicMock()
        mock_process.stdout = MagicMock()

        with patch("subprocess.Popen", return_value=mock_process):
            await connector._spawn_gemini_cli_process()

            assert connector._process is not None
            assert connector._process == mock_process

    async def test_spawn_process_already_running(self, connector, temp_workspace):
        """Test spawning process when already running does nothing."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_process.poll.return_value = None

        connector._process = mock_process

        with patch("subprocess.Popen") as mock_popen:
            await connector._spawn_gemini_cli_process()
            mock_popen.assert_not_called()

    async def test_kill_process_success(self, connector, temp_workspace):
        """Test killing the gemini-cli process."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        connector._process = mock_process

        await connector._kill_process()

        mock_process.terminate.assert_called_once()
        assert connector._process is None

    async def test_kill_process_force_kill_on_timeout(self, connector, temp_workspace):
        """Test force killing process when terminate times out."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_process.wait.side_effect = subprocess.TimeoutExpired("gemini", 5)
        connector._process = mock_process

        await connector._kill_process()

        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()


class TestGeminiCliAcpConnectorProjectDirControl:
    """Test project directory control mechanisms."""

    async def test_change_project_dir_success(self, connector, temp_workspace, tmp_path):
        """Test changing project directory successfully."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        # Create new workspace
        new_workspace = tmp_path / "new_workspace"
        new_workspace.mkdir()

        # Mock process
        mock_process = MagicMock()
        connector._process = mock_process

        await connector.change_project_dir(str(new_workspace))

        assert connector._project_dir == new_workspace.resolve()
        mock_process.terminate.assert_called_once()

    async def test_change_project_dir_nonexistent_directory(
        self, connector, temp_workspace
    ):
        """Test changing to nonexistent project directory fails."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        with pytest.raises(ConfigurationError) as exc_info:
            await connector.change_project_dir("/nonexistent/path")

        assert "Project directory does not exist" in str(exc_info.value)

    async def test_change_project_dir_same_path_no_op(self, connector, temp_workspace):
        """Test changing to same project directory is no-op."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        connector._process = mock_process

        await connector.change_project_dir(str(temp_workspace))

        # Process should not be terminated
        mock_process.terminate.assert_not_called()


class TestGeminiCliAcpConnectorCommunication:
    """Test JSON-RPC communication functionality."""

    async def test_send_jsonrpc_message_success(self, connector, temp_workspace):
        """Test sending a JSON-RPC message successfully."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_stdin = MagicMock()
        mock_process.stdin = mock_stdin
        connector._process = mock_process

        await connector._send_jsonrpc_message("test_method", {"key": "value"})

        mock_stdin.write.assert_called_once()
        mock_stdin.flush.assert_called_once()

    async def test_send_jsonrpc_message_no_process(self, connector):
        """Test sending message without process raises error."""
        with pytest.raises(BackendError) as exc_info:
            await connector._send_jsonrpc_message("test", {})

        assert "gemini-cli process not running" in str(exc_info.value)

    async def test_read_jsonrpc_response_success(self, connector, temp_workspace):
        """Test reading a JSON-RPC response successfully."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.readline.return_value = b'{"result": "success"}\n'
        mock_process.stdout = mock_stdout
        connector._process = mock_process

        loop = asyncio.get_event_loop()
        with patch("asyncio.get_event_loop", return_value=loop):
            response = await connector._read_jsonrpc_response()

        assert response == {"result": "success"}

    async def test_read_jsonrpc_response_invalid_json(self, connector, temp_workspace):
        """Test reading invalid JSON raises error."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        mock_process = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.readline.return_value = b"invalid json\n"
        mock_process.stdout = mock_stdout
        connector._process = mock_process

        loop = asyncio.get_event_loop()
        with (
            patch("asyncio.get_event_loop", return_value=loop),
            pytest.raises(BackendError) as exc_info,
        ):
            await connector._read_jsonrpc_response()

        assert "Invalid JSON response" in str(exc_info.value)


class TestGeminiCliAcpConnectorChatCompletions:
    """Test chat completions functionality."""

    async def test_chat_completions_not_initialized(self, connector):
        """Test chat completions fail when not initialized."""
        request_data = MagicMock()
        request_data.stream = False

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await connector.chat_completions(
                request_data=request_data,
                processed_messages=[],
                effective_model="gemini-2.5-flash",
            )

        assert "not initialized" in str(exc_info.value)

    async def test_chat_completions_project_dir_change_detection(
        self, connector, temp_workspace, tmp_path
    ):
        """Test chat completions detects project directory change from session."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        # Create new workspace
        new_workspace = tmp_path / "session_workspace"
        new_workspace.mkdir()

        request_data = MagicMock()
        request_data.stream = False

        # Mock all the required methods
        with (
            patch.object(connector, "change_project_dir", new=AsyncMock()) as mock_change,
            patch.object(connector, "_spawn_gemini_cli_process", new=AsyncMock()),
            patch.object(connector, "_initialize_agent", new=AsyncMock()),
            patch.object(connector, "_send_jsonrpc_message", new=AsyncMock()),
            patch.object(connector, "_process_streaming_response") as mock_stream,
        ):
            # Mock streaming response generator
            async def mock_generator():
                yield ProcessedResponse(
                    content='data: {"choices": [{"delta": {"content": "test"}}]}\n\n'
                )

            mock_stream.return_value = mock_generator()

            with contextlib.suppress(Exception):
                await connector.chat_completions(
                    request_data=request_data,
                    processed_messages=[{"role": "user", "content": "hello"}],
                    effective_model="gemini-2.5-flash",
                    project=str(new_workspace),  # Simulating session project_dir
                )

            mock_change.assert_called_once_with(str(new_workspace))


class TestGeminiCliAcpConnectorStreaming:
    """Test streaming response processing."""

    async def test_process_streaming_response_text_part(
        self, connector, temp_workspace
    ):
        """Test processing streaming response with text parts."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        # Mock _read_jsonrpc_response to return text response then None to end
        responses = [
            {"result": {"Message": "Hello, world!"}},
            None,  # End stream
        ]
        response_iter = iter(responses)

        async def mock_read():
            return next(response_iter)

        with patch.object(connector, "_read_jsonrpc_response", side_effect=mock_read):
            chunks = []
            async for chunk in connector._process_streaming_response(
                "gemini-2.5-flash"
            ):
                chunks.append(chunk)

            # Should have received text chunk + done chunk
            assert len(chunks) >= 2
            assert any("Hello, world!" in chunk.content for chunk in chunks)

    async def test_process_streaming_response_timeout(self, connector, temp_workspace):
        """Test streaming response timeout handling."""
        with patch.object(connector, "_check_gemini_cli_available", return_value=True):
            await connector.initialize(project_dir=str(temp_workspace))

        connector._process_timeout = 0.1  # Very short timeout

        async def mock_read_slow():
            await asyncio.sleep(1)  # Sleep longer than timeout
            return {"result": {}}

        with (
            patch.object(
                connector, "_read_jsonrpc_response", side_effect=mock_read_slow
            ),
            pytest.raises(APITimeoutError),
        ):
            async for _ in connector._process_streaming_response("gemini-2.5-flash"):
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
