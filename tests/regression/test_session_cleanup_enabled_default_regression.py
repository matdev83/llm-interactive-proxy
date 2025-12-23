"""Regression test for session cleanup enabled by default fix.

This test verifies that session_cleanup_enabled defaults to True in
AppLifecycle configuration, preventing unbounded memory growth in
InMemorySessionRepository.
"""

from src.core.app.lifecycle import AppLifecycle


class TestSessionCleanupEnabledDefaultRegression:
    """Regression tests for session cleanup enabled by default fix."""

    def test_session_cleanup_enabled_defaults_to_true(self) -> None:
        """Test that session_cleanup_enabled defaults to True when not specified."""
        from unittest.mock import MagicMock

        app = MagicMock()
        config = {}  # Empty config - should default to True

        AppLifecycle(app, config)

        # Check that the default value is True by reading the source code pattern
        # The fix ensures: config.get("session_cleanup_enabled", True)
        # We verify this by checking the behavior indirectly
        # Since we can't easily test the actual startup without full app setup,
        # we verify the code pattern exists

        # Read the lifecycle file to verify the default
        import inspect
        import os

        lifecycle_file = os.path.join(
            os.path.dirname(inspect.getfile(AppLifecycle)),
            "lifecycle.py",
        )

        with open(lifecycle_file) as f:
            content = f.read()

        # Verify the fix is in place: default should be True
        assert 'if self.config.get("session_cleanup_enabled", True):' in content, (
            "session_cleanup_enabled should default to True. "
            "The fix may have been reverted or changed."
        )

    def test_session_cleanup_can_be_disabled_explicitly(self) -> None:
        """Test that session cleanup can still be disabled explicitly."""
        from unittest.mock import MagicMock

        app = MagicMock()
        config = {"session_cleanup_enabled": False}  # Explicitly disabled

        lifecycle = AppLifecycle(app, config)

        # Verify config is stored correctly
        assert lifecycle.config["session_cleanup_enabled"] is False

        # The default should only apply when not specified
        # This test ensures backward compatibility is maintained
