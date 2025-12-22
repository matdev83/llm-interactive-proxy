"""Regression test for ModelReplacementService session states memory leak fix.

This test verifies that session states and disabled sessions are cleaned up
when cleanup_session() is called to prevent unbounded memory growth.
"""

import pytest

from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.services.model_replacement_service import ModelReplacementService
from src.core.services.replacement_metrics import ReplacementMetrics


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def get_registered_backends(self) -> list[str]:
        return ["openai", "gemini"]


class TestModelReplacementSessionStatesLeakRegression:
    """Regression tests for ModelReplacementService session states leak fix."""

    @pytest.fixture
    def service(self) -> ModelReplacementService:
        """Create ModelReplacementService for testing."""
        config = ReplacementConfig(
            enabled=True,
            probability=0.5,
            backend_model="gemini:gemini-pro",
            turn_count=3,
        )
        registry = MockBackendRegistry()
        return ModelReplacementService(config, registry)

    @pytest.mark.asyncio
    async def test_session_states_cleaned_up(self, service: ModelReplacementService) -> None:
        """Test that session states are cleaned up when cleanup_session() is called."""
        session_id = "test-session"

        # Create a minimal mock RequestContext
        class MockRequestContext:
            def get_header(self, name: str, default: str = "") -> str:
                return default

        ctx = MockRequestContext()

        # Create state by calling should_replace
        service.should_replace(session_id, ctx)

        # Verify state exists
        assert session_id in service._session_states, "Session state should exist"

        # Cleanup session
        service.cleanup_session(session_id)

        # Verify state is removed
        assert session_id not in service._session_states, (
            "Session state should be removed after cleanup"
        )

    @pytest.mark.asyncio
    async def test_disabled_sessions_cleaned_up(
        self, service: ModelReplacementService
    ) -> None:
        """Test that disabled sessions are cleaned up when cleanup_session() is called."""
        session_id = "test-session"

        # Disable session
        service.disable_for_session(session_id)

        # Verify disabled session exists
        assert session_id in service._disabled_sessions, "Disabled session should exist"

        # Cleanup session
        service.cleanup_session(session_id)

        # Verify disabled session is removed
        assert session_id not in service._disabled_sessions, (
            "Disabled session should be removed after cleanup"
        )

    @pytest.mark.asyncio
    async def test_multiple_sessions_cleaned_up(
        self, service: ModelReplacementService
    ) -> None:
        """Test that multiple sessions can be cleaned up."""
        num_sessions = 100

        class MockRequestContext:
            def get_header(self, name: str, default: str = "") -> str:
                return default

        ctx = MockRequestContext()

        # Create many sessions
        for i in range(num_sessions):
            session_id = f"session-{i}"
            service.should_replace(session_id, ctx)
            if i % 10 == 0:
                service.disable_for_session(session_id)

        # Verify states exist
        assert len(service._session_states) == num_sessions, (
            f"Expected {num_sessions} session states, got {len(service._session_states)}"
        )
        assert len(service._disabled_sessions) == num_sessions // 10, (
            f"Expected {num_sessions // 10} disabled sessions, "
            f"got {len(service._disabled_sessions)}"
        )

        # Cleanup all sessions
        for i in range(num_sessions):
            session_id = f"session-{i}"
            service.cleanup_session(session_id)

        # Verify all states are removed
        assert len(service._session_states) == 0, (
            f"Expected 0 session states after cleanup, got {len(service._session_states)}"
        )
        assert len(service._disabled_sessions) == 0, (
            f"Expected 0 disabled sessions after cleanup, "
            f"got {len(service._disabled_sessions)}"
        )

    @pytest.mark.asyncio
    async def test_cleanup_session_idempotent(
        self, service: ModelReplacementService
    ) -> None:
        """Test that cleanup_session() can be called multiple times safely."""
        session_id = "test-session"

        class MockRequestContext:
            def get_header(self, name: str, default: str = "") -> str:
                return default

        ctx = MockRequestContext()
        service.should_replace(session_id, ctx)
        service.disable_for_session(session_id)

        # Cleanup multiple times
        service.cleanup_session(session_id)
        service.cleanup_session(session_id)
        service.cleanup_session(session_id)

        # Should not raise exception and should be idempotent
        assert session_id not in service._session_states, (
            "Session state should be removed after cleanup"
        )
        assert session_id not in service._disabled_sessions, (
            "Disabled session should be removed after cleanup"
        )
