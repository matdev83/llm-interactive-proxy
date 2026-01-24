"""Integration tests for replacement metrics tracking in ModelReplacementService.

Tests verify that metrics are correctly tracked during actual service operations:
- Activation rate tracking (Requirement 3.2)
- Turn count distribution tracking (Requirement 4.1)
- Opt-out rate tracking (Requirements 9.1, 9.2)
"""

from __future__ import annotations

import pytest
from src.core.domain.configuration.replacement_config import ReplacementConfig
from src.core.domain.request_context import RequestContext
from src.core.services.model_replacement_service import ModelReplacementService


class MockBackendRegistry:
    """Mock backend registry for testing."""

    def __init__(self, backends: list[str] | None = None) -> None:
        """Initialize with optional list of backend names."""
        self._backends = set(backends or [])

    def register_backend(self, backend_name: str) -> None:
        """Register a backend."""
        self._backends.add(backend_name)

    def get_registered_backends(self) -> list[str]:
        """Get list of registered backends."""
        return list(self._backends)

    def is_backend_registered(self, backend_name: str) -> bool:
        """Check if a backend is registered."""
        return backend_name in self._backends


class TestReplacementMetricsIntegration:
    """Integration tests for metrics tracking in ModelReplacementService."""

    @pytest.fixture
    def backend_registry(self) -> MockBackendRegistry:
        """Create a mock backend registry."""
        registry = MockBackendRegistry()
        registry.register_backend("anthropic")
        registry.register_backend("qwen-oauth")
        return registry

    @pytest.fixture
    def config(self) -> ReplacementConfig:
        """Create a replacement configuration."""
        return ReplacementConfig(
            enabled=True,
            probability=1.0,  # Always activate for testing
            backend_model="qwen-oauth:qwen3-coder-plus",
            turn_count=3,
        )

    @pytest.fixture
    def service(
        self, config: ReplacementConfig, backend_registry: MockBackendRegistry
    ) -> ModelReplacementService:
        """Create a model replacement service."""
        return ModelReplacementService(
            config=config,
            backend_registry=backend_registry,
        )

    @pytest.fixture
    def request_context(self) -> RequestContext:
        """Create a request context."""
        return RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="test-session",
        )

    def test_activation_metrics_tracked(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that activation metrics are tracked correctly."""
        # Check if replacement should be triggered
        service.should_replace("session1", request_context)  # Prime session
        should_replace = service.should_replace("session1", request_context)
        assert should_replace

        # Get metrics before activation
        metrics = service.get_metrics()
        assert metrics.total_activations == 0

        # Activate replacement
        import asyncio

        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )

        # Verify activation was tracked
        assert metrics.total_activations == 1
        assert metrics.activations_by_session["session1"] == 1
        assert len(metrics.activation_timestamps) == 1
        # Turn counts are tracked in histogram, not as a list
        assert metrics.get_turn_count_distribution()[3] == 1

    def test_turn_completion_metrics_tracked(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that turn completion metrics are tracked correctly."""
        # Activate replacement
        import asyncio

        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )

        metrics = service.get_metrics()
        assert metrics.total_turns_completed == 0

        # Complete a turn
        service.complete_turn("session1")

        # Verify turn completion was tracked
        assert metrics.total_turns_completed == 1
        assert metrics.turns_by_session["session1"] == 1

    def test_multiple_turn_completions_tracked(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that multiple turn completions are tracked correctly."""
        # Activate replacement
        import asyncio

        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )

        metrics = service.get_metrics()

        # Complete multiple turns
        service.complete_turn("session1")
        service.complete_turn("session1")
        service.complete_turn("session1")

        # Verify all turns were tracked
        assert metrics.total_turns_completed == 3
        assert metrics.turns_by_session["session1"] == 3

    def test_header_opt_out_metrics_tracked(
        self,
        service: ModelReplacementService,
    ) -> None:
        """Test that header-based opt-out metrics are tracked correctly."""
        # Create request context with opt-out header
        context = RequestContext(
            headers={"x-disable-replacement": "true"},
            cookies={},
            state=None,
            app_state=None,
            session_id="test-session",
        )

        metrics = service.get_metrics()
        assert metrics.total_opt_outs == 0

        # Check if replacement should be triggered (should be False due to opt-out)
        should_replace = service.should_replace("session1", context)
        assert not should_replace

        # Verify opt-out was tracked
        assert metrics.total_opt_outs == 1
        assert metrics.header_opt_outs == 1
        assert metrics.session_opt_outs == 0
        assert metrics.opt_outs_by_session["session1"] == 1

    def test_session_opt_out_metrics_tracked(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that session-level opt-out metrics are tracked correctly."""
        metrics = service.get_metrics()
        assert metrics.total_opt_outs == 0

        # Disable replacement for session
        service.disable_for_session("session1")

        # Check if replacement should be triggered (should be False due to opt-out)
        should_replace = service.should_replace("session1", request_context)
        assert not should_replace

        # Verify opt-out was tracked
        assert metrics.total_opt_outs == 1
        assert metrics.header_opt_outs == 0
        assert metrics.session_opt_outs == 1
        assert metrics.opt_outs_by_session["session1"] == 1

    def test_probability_check_metrics_tracked(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that probability check metrics are tracked correctly."""
        metrics = service.get_metrics()
        assert metrics.total_probability_checks == 0

        # Check if replacement should be triggered
        service.should_replace("session1", request_context)  # First turn skip
        service.should_replace("session1", request_context)  # Actual check

        # Verify probability check was tracked
        assert metrics.total_probability_checks == 1
        assert metrics.probability_checks_by_session["session1"] == 1

    def test_multiple_sessions_tracked_independently(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that metrics for multiple sessions are tracked independently."""
        import asyncio

        # Activate replacement for session1
        service.should_replace("session1", request_context)
        service.should_replace("session1", request_context)  # Trigger probability check
        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )
        service.complete_turn("session1")

        # Activate replacement for session2
        service.should_replace("session2", request_context)
        service.should_replace("session2", request_context)  # Trigger probability check
        asyncio.run(
            service.activate_replacement("session2", "anthropic", "claude-3-5-sonnet")
        )
        service.complete_turn("session2")
        service.complete_turn("session2")

        metrics = service.get_metrics()

        # Verify session-specific metrics
        assert metrics.activations_by_session["session1"] == 1
        assert metrics.activations_by_session["session2"] == 1
        assert metrics.turns_by_session["session1"] == 1
        assert metrics.turns_by_session["session2"] == 2
        assert metrics.probability_checks_by_session["session1"] == 1
        assert metrics.probability_checks_by_session["session2"] == 1

    def test_activation_rate_calculation(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that activation rate is calculated correctly."""
        import asyncio

        # Record multiple activations
        for i in range(5):
            service.should_replace(f"session{i}", request_context)
            asyncio.run(
                service.activate_replacement(
                    f"session{i}", "anthropic", "claude-3-5-sonnet"
                )
            )

        metrics = service.get_metrics()

        # Get activation rate
        rate = metrics.get_activation_rate()

        # Rate should be positive
        assert rate > 0

    def test_turn_count_distribution_calculation(
        self,
        backend_registry: MockBackendRegistry,
    ) -> None:
        """Test that turn count distribution is calculated correctly."""
        import asyncio

        # Create services with different turn counts
        config1 = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="qwen-oauth:qwen3-coder-plus",
            turn_count=3,
        )
        service1 = ModelReplacementService(
            config=config1,
            backend_registry=backend_registry,
        )

        config2 = ReplacementConfig(
            enabled=True,
            probability=1.0,
            backend_model="qwen-oauth:qwen3-coder-plus",
            turn_count=5,
        )
        service2 = ModelReplacementService(
            config=config2,
            backend_registry=backend_registry,
        )

        # Activate replacements
        asyncio.run(
            service1.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )
        asyncio.run(
            service1.activate_replacement("session2", "anthropic", "claude-3-5-sonnet")
        )
        asyncio.run(
            service2.activate_replacement("session3", "anthropic", "claude-3-5-sonnet")
        )

        # Get distribution from service1
        metrics1 = service1.get_metrics()
        distribution1 = metrics1.get_turn_count_distribution()

        # Verify distribution
        assert distribution1[3] == 2  # Two activations with 3 turns

        # Get distribution from service2
        metrics2 = service2.get_metrics()
        distribution2 = metrics2.get_turn_count_distribution()

        # Verify distribution
        assert distribution2[5] == 1  # One activation with 5 turns

    def test_opt_out_rate_calculation(
        self,
        service: ModelReplacementService,
    ) -> None:
        """Test that opt-out rate is calculated correctly."""
        # Record multiple opt-outs
        for i in range(3):
            context = RequestContext(
                headers={"x-disable-replacement": "true"},
                cookies={},
                state=None,
                app_state=None,
                session_id="test-session",
            )
            service.should_replace(f"session{i}", context)

        metrics = service.get_metrics()

        # Get opt-out rate
        rate = metrics.get_opt_out_rate()

        # Rate should be positive
        assert rate > 0

    def test_metrics_summary_generation(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that metrics summary is generated correctly."""
        import asyncio

        # Record various events
        service.should_replace("session1", request_context)
        service.should_replace("session1", request_context)  # Trigger probability check
        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )
        service.complete_turn("session1")

        context_with_opt_out = RequestContext(
            headers={"x-disable-replacement": "true"},
            cookies={},
            state=None,
            app_state=None,
            session_id="test-session",
        )
        service.should_replace("session2", context_with_opt_out)

        # Get summary
        metrics = service.get_metrics()
        summary = metrics.get_summary()

        # Verify summary structure
        assert "activation_metrics" in summary
        assert "turn_count_metrics" in summary
        assert "opt_out_metrics" in summary
        assert "probability_check_metrics" in summary

        # Verify values
        assert summary["activation_metrics"]["total_activations"] == 1
        assert summary["turn_count_metrics"]["total_turns_completed"] == 1
        assert summary["opt_out_metrics"]["total_opt_outs"] == 1
        # Only one probability check was made (for session1), session2 opted out before probability check
        assert summary["probability_check_metrics"]["total_probability_checks"] == 1

    def test_metrics_reset(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that metrics can be reset."""
        import asyncio

        # Record some events
        service.should_replace("session1", request_context)
        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )
        service.complete_turn("session1")

        metrics = service.get_metrics()
        assert metrics.total_activations > 0

        # Reset metrics
        service.reset_metrics()

        # Verify metrics are reset
        assert metrics.total_activations == 0
        assert metrics.total_turns_completed == 0
        assert metrics.total_opt_outs == 0

    def test_metrics_logging_does_not_crash(
        self,
        service: ModelReplacementService,
        request_context: RequestContext,
    ) -> None:
        """Test that metrics logging does not crash."""
        import asyncio

        # Record some events
        service.should_replace("session1", request_context)
        asyncio.run(
            service.activate_replacement("session1", "anthropic", "claude-3-5-sonnet")
        )

        # Should not raise any exceptions
        service.log_metrics_summary()
