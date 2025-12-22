"""Regression test for Gemini TokenManager subprocess leak fix.

This test verifies that TokenManager properly cleans up subprocesses
when destroyed, preventing subprocess leaks if connector's __del__ fails.

Fixed: Added __del__ method to TokenManager to cleanup CLI refresh subprocess.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.connectors.gemini_base.token_manager import TokenManager


class TestGeminiTokenManagerSubprocessLeakRegression:
    """Regression tests for TokenManager subprocess leak fix."""

    def test_token_manager_has_del_method(self) -> None:
        """Test that TokenManager has __del__ method for automatic cleanup."""
        assert hasattr(TokenManager, "__del__"), (
            "TokenManager should have __del__ method to cleanup subprocesses on destruction"
        )

    def test_del_method_cleans_up_subprocess(self) -> None:
        """Test that __del__ method properly cleans up subprocess."""
        # Create a mock subprocess
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running

        # Create TokenManager instance
        manager = TokenManager()
        manager._cli_refresh_process = mock_process

        # Call __del__ method
        manager.__del__()

        # Verify process was terminated
        assert mock_process.terminate.called or mock_process.kill.called, (
            "Process should be terminated in __del__"
        )
        assert manager._cli_refresh_process is None, (
            "Process reference should be cleared in __del__"
        )

    def test_del_method_handles_none_process(self) -> None:
        """Test that __del__ method handles None process gracefully."""
        manager = TokenManager()
        manager._cli_refresh_process = None

        # Should not raise exception
        manager.__del__()

    def test_del_method_handles_already_terminated_process(self) -> None:
        """Test that __del__ method handles already terminated process."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 0  # Process already terminated

        manager = TokenManager()
        manager._cli_refresh_process = mock_process

        # Should not attempt to terminate already terminated process
        manager.__del__()

        # Process reference should still be cleared
        assert manager._cli_refresh_process is None

    def test_del_method_handles_exceptions_gracefully(self) -> None:
        """Test that __del__ method handles exceptions gracefully."""
        mock_process = MagicMock()
        mock_process.poll.side_effect = Exception("Poll failed")
        mock_process.terminate.side_effect = Exception("Terminate failed")

        manager = TokenManager()
        manager._cli_refresh_process = mock_process

        # Should not raise exception even if cleanup fails
        manager.__del__()

        # Process reference should still be cleared
        assert manager._cli_refresh_process is None

    def test_del_method_handles_timeout(self) -> None:
        """Test that __del__ method handles process termination timeout."""
        import subprocess

        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process is running
        mock_process.terminate.return_value = None
        mock_process.wait.side_effect = subprocess.TimeoutExpired("wait", 5)

        manager = TokenManager()
        manager._cli_refresh_process = mock_process

        # Should attempt kill after timeout
        manager.__del__()

        # Should attempt kill after terminate timeout
        assert mock_process.kill.called, "Should attempt kill after terminate timeout"

    def test_del_method_handles_partial_initialization(self) -> None:
        """Test that __del__ method handles partial initialization gracefully."""
        # Create manager without _cli_refresh_process attribute
        manager = TokenManager()

        # Should not raise AttributeError
        manager.__del__()
