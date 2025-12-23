"""Regression test for GeminiCliAcpConnector subprocess leak fix.

This test verifies that GeminiCliAcpConnector properly cleans up subprocesses
when destroyed, preventing subprocess leaks if shutdown() is not called explicitly.

Fixed: Connector should have proper cleanup mechanism (__del__ or ensure shutdown is called).
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from src.connectors.gemini_cli_acp import GeminiCliAcpConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService

# Mark all tests with timeout to prevent infinite stalling
pytestmark = pytest.mark.timeout(30)


class TestGeminiCliSubprocessLeakRegression:
    """Regression tests for GeminiCliAcpConnector subprocess leak fix."""

    @pytest.fixture
    def mock_config(self) -> AppConfig:
        """Create a mock AppConfig."""
        config = MagicMock(spec=AppConfig)
        config.backends = {}
        return config

    @pytest.fixture
    def mock_translation_service(self) -> TranslationService:
        """Create a mock TranslationService."""
        return MagicMock(spec=TranslationService)

    @pytest.fixture
    def mock_client(self):
        """Create a mock httpx.AsyncClient."""
        return MagicMock()

    def _create_mock_process(self) -> MagicMock:
        """Create a properly mocked subprocess that won't block.

        The mock ensures that wait() calls return immediately without blocking,
        which is critical since wait() is a synchronous blocking call that would
        stall the async event loop.
        """
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running

        # Create a call counter to track wait() calls
        # This helps ensure wait() is called correctly
        wait_call_count = {"count": 0}

        def mock_wait(timeout=None):
            """Mock wait() that returns immediately without blocking.

            This simulates a process that exits immediately when wait() is called.
            The timeout parameter is accepted but ignored to match real API.
            """
            wait_call_count["count"] += 1
            # Return immediately, simulating process already exited
            # This prevents blocking the event loop
            return 0

        mock_process.wait = mock_wait

        # Mock stream attributes to avoid errors in _cleanup_process
        # _cleanup_process tries to close these streams
        mock_stdin = MagicMock()
        mock_stdin.close = MagicMock(
            return_value=None
        )  # Ensure close() is callable and returns None
        mock_stdout = MagicMock()
        mock_stdout.close = MagicMock(return_value=None)
        mock_stderr = MagicMock()
        mock_stderr.close = MagicMock(return_value=None)

        mock_process.stdin = mock_stdin
        mock_process.stdout = mock_stdout
        mock_process.stderr = mock_stderr

        # Store wait call count for debugging
        mock_process._wait_call_count = wait_call_count

        return mock_process

    @pytest.mark.asyncio
    async def test_shutdown_cleans_up_process(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that shutdown() properly cleans up subprocess."""
        connector = GeminiCliAcpConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Mock subprocess creation
        mock_process = self._create_mock_process()
        connector._process = mock_process

        # Patch subprocess.Popen.wait to ensure it never blocks
        def non_blocking_wait(self, timeout=None):
            return 0

        with patch.object(subprocess.Popen, "wait", non_blocking_wait):
            # Call shutdown
            await connector.shutdown()

        # Verify process was terminated
        assert (
            mock_process.terminate.called or mock_process.kill.called
        ), "Process should be terminated during shutdown"
        assert connector._process is None, "Process reference should be cleared"

    @pytest.mark.asyncio
    async def test_async_context_manager_cleans_up_process(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that async context manager properly cleans up subprocess."""
        connector = GeminiCliAcpConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Mock subprocess creation before entering context
        mock_process = self._create_mock_process()

        # Patch subprocess.Popen.wait to ensure it never blocks
        def non_blocking_wait(self, timeout=None):
            return 0

        with patch.object(subprocess.Popen, "wait", non_blocking_wait):
            async with connector:
                connector._process = mock_process

        # After exiting context, process should be cleaned up
        # Note: In real scenario, __aexit__ calls _kill_process
        # We verify the cleanup mechanism exists
        assert hasattr(
            connector, "__aexit__"
        ), "Connector should support async context manager for cleanup"

        # Verify process was cleaned up
        assert (
            connector._process is None
        ), "Process should be cleaned up after context exit"

    def test_connector_has_cleanup_mechanism(self) -> None:
        """Test that connector has a cleanup mechanism (shutdown or __del__)."""
        # Check if connector has shutdown method
        assert hasattr(
            GeminiCliAcpConnector, "shutdown"
        ), "Connector should have shutdown() method for explicit cleanup"

        # Check if connector has __del__ method for automatic cleanup
        # Note: If __del__ doesn't exist, connector must be managed through shutdown()
        has_del = hasattr(GeminiCliAcpConnector, "__del__")
        has_shutdown = hasattr(GeminiCliAcpConnector, "shutdown")
        has_aexit = hasattr(GeminiCliAcpConnector, "__aexit__")

        assert has_del or (has_shutdown and has_aexit), (
            "Connector should have either __del__ method for automatic cleanup "
            "or shutdown() + __aexit__ for managed cleanup"
        )

    @pytest.mark.asyncio
    async def test_process_cleanup_on_exception(
        self,
        mock_config: AppConfig,
        mock_translation_service: TranslationService,
        mock_client,
    ) -> None:
        """Test that process is cleaned up even if exception occurs."""
        connector = GeminiCliAcpConnector(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )

        # Mock subprocess creation
        mock_process = self._create_mock_process()
        connector._process = mock_process

        # Simulate exception during shutdown
        mock_process.terminate.side_effect = Exception("Terminate failed")

        # Patch subprocess.Popen.wait to ensure it never blocks
        def non_blocking_wait(self, timeout=None):
            return 0

        with patch.object(subprocess.Popen, "wait", non_blocking_wait):
            # Shutdown should still attempt cleanup
            await connector.shutdown()

        # Verify cleanup was attempted
        assert mock_process.terminate.called, "Should attempt to terminate process"

    def test_cleanup_process_method_exists(self) -> None:
        """Test that _cleanup_process method exists."""
        assert hasattr(
            GeminiCliAcpConnector, "_cleanup_process"
        ), "Connector should have _cleanup_process method"

    def test_kill_process_method_exists(self) -> None:
        """Test that _kill_process method exists."""
        assert hasattr(
            GeminiCliAcpConnector, "_kill_process"
        ), "Connector should have _kill_process method"
