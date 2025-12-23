"""Regression test for QwenOAuthConnector subprocess leak fix.

This test verifies that QwenOAuthConnector properly cleans up subprocesses
when destroyed, preventing subprocess leaks if shutdown() is not called explicitly.

Fixed: Added __del__ method to cleanup CLI refresh subprocess on destruction.
"""

from unittest.mock import MagicMock

import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


class TestQwenSubprocessLeakRegression:
    """Regression tests for QwenOAuthConnector subprocess leak fix."""

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

    def test_connector_has_del_method(self) -> None:
        """Test that connector has __del__ method for automatic cleanup."""
        assert hasattr(
            QwenOAuthConnector, "__del__"
        ), "Connector should have __del__ method to cleanup subprocesses on destruction"

    def test_del_method_cleans_up_subprocess(self) -> None:
        """Test that __del__ method properly cleans up subprocess."""
        # Create a mock subprocess
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running

        # Create connector instance
        connector = QwenOAuthConnector(
            client=MagicMock(),
            config=MagicMock(spec=AppConfig),
            translation_service=MagicMock(spec=TranslationService),
        )
        connector._cli_refresh_process = mock_process

        # Call __del__ method
        connector.__del__()

        # Verify process was terminated
        assert (
            mock_process.terminate.called or mock_process.kill.called
        ), "Process should be terminated in __del__"
        assert (
            connector._cli_refresh_process is None
        ), "Process reference should be cleared in __del__"

    def test_del_method_handles_none_process(self) -> None:
        """Test that __del__ method handles None process gracefully."""
        connector = QwenOAuthConnector(
            client=MagicMock(),
            config=MagicMock(spec=AppConfig),
            translation_service=MagicMock(spec=TranslationService),
        )
        connector._cli_refresh_process = None

        # Should not raise exception
        connector.__del__()

    def test_del_method_handles_already_terminated_process(self) -> None:
        """Test that __del__ method handles already terminated process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Process already terminated

        connector = QwenOAuthConnector(
            client=MagicMock(),
            config=MagicMock(spec=AppConfig),
            translation_service=MagicMock(spec=TranslationService),
        )
        connector._cli_refresh_process = mock_process

        # Should not attempt to terminate already terminated process
        connector.__del__()

        # Process reference should still be cleared
        assert connector._cli_refresh_process is None

    def test_del_method_handles_exceptions_gracefully(self) -> None:
        """Test that __del__ method handles exceptions gracefully."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = Exception("Poll failed")
        mock_process.terminate.side_effect = Exception("Terminate failed")

        connector = QwenOAuthConnector(
            client=MagicMock(),
            config=MagicMock(spec=AppConfig),
            translation_service=MagicMock(spec=TranslationService),
        )
        connector._cli_refresh_process = mock_process

        # Should not raise exception even if cleanup fails
        connector.__del__()

        # Process reference should still be cleared
        assert connector._cli_refresh_process is None

    def test_del_method_handles_timeout(self) -> None:
        """Test that __del__ method handles process termination timeout."""
        import subprocess

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running
        mock_process.terminate.return_value = None
        mock_process.wait.side_effect = subprocess.TimeoutExpired("wait", 5)

        connector = QwenOAuthConnector(
            client=MagicMock(),
            config=MagicMock(spec=AppConfig),
            translation_service=MagicMock(spec=TranslationService),
        )
        connector._cli_refresh_process = mock_process

        # Should attempt kill after timeout
        connector.__del__()

        # Should attempt kill after terminate timeout
        assert mock_process.kill.called, "Should attempt kill after terminate timeout"
