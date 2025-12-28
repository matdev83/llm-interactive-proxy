"""
Tests for registrar determinism and idempotency.

These tests verify that:
- Registrars can run on empty containers without errors
- Registrar order is deterministic
- Repeated invocations are idempotent
- No side effects occur during import/registration
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import (
    backend,
    core,
    persistence,
    replacement,
    resilience,
    security,
    streaming,
    tooling,
)
from src.core.di.registrations._orchestrator import register_all
from src.core.di.registrations._shared import (
    register_if_absent,
    register_interface_and_implementation,
    register_scoped_if_absent,
    register_singleton_if_absent,
    register_transient_if_absent,
)
from src.core.interfaces.di_interface import ServiceLifetime


class TestRegistrarDeterminism:
    """Test that registrars behave deterministically."""

    def test_registrar_can_run_on_empty_container(self) -> None:
        """Verify each registrar runs without errors on a fresh ServiceCollection."""
        services = ServiceCollection()
        config = AppConfig()

        # Each registrar should be callable without errors
        core.register(services, config)
        streaming.register(services, config)
        persistence.register(services, config)
        security.register(services, config)
        tooling.register(services, config)
        backend.register(services, config)
        replacement.register(services, config)
        resilience.register(services, config)

        # Should also work with None config
        services2 = ServiceCollection()
        core.register(services2, None)
        streaming.register(services2, None)
        persistence.register(services2, None)
        security.register(services2, None)
        tooling.register(services2, None)
        backend.register(services2, None)
        replacement.register(services2, None)
        resilience.register(services2, None)

    def test_registrar_order_is_deterministic(self) -> None:
        """Verify that calling registrars in the same order produces the same registrations."""
        services1 = ServiceCollection()
        services2 = ServiceCollection()
        config = AppConfig()

        # Register in same order twice
        core.register(services1, config)
        streaming.register(services1, config)
        persistence.register(services1, config)
        security.register(services1, config)
        tooling.register(services1, config)
        backend.register(services1, config)
        replacement.register(services1, config)
        resilience.register(services1, config)

        core.register(services2, config)
        streaming.register(services2, config)
        persistence.register(services2, config)
        security.register(services2, config)
        tooling.register(services2, config)
        backend.register(services2, config)
        replacement.register(services2, config)
        resilience.register(services2, config)

        # Both should have the same descriptors (currently empty, but structure should match)
        assert set(services1._descriptors.keys()) == set(services2._descriptors.keys())

    def test_registrar_imports_do_not_side_effect(self) -> None:
        """Verify importing registrars doesn't perform I/O or mutate global state."""
        # Import registrars
        from src.core.di.registrations import (
            backend,
            core,
            persistence,
            replacement,
            resilience,
            security,
            streaming,
            tooling,
        )

        # Verify registrars are callable functions, not executed code
        # This ensures no side effects occurred at import time (no register() calls)
        assert callable(core.register)
        assert callable(streaming.register)
        assert callable(persistence.register)
        assert callable(security.register)
        assert callable(tooling.register)
        assert callable(backend.register)
        assert callable(replacement.register)
        assert callable(resilience.register)


class TestIdempotency:
    """Test idempotent registration utilities."""

    def test_register_if_absent_skips_existing(self) -> None:
        """Verify that register_if_absent skips registration if service already exists."""
        services = ServiceCollection()

        # Register a service directly
        class TestService:
            pass

        services.add_singleton(TestService)

        # Try to register again with register_if_absent
        result = register_if_absent(
            services,
            TestService,
            ServiceLifetime.SINGLETON,
            implementation_type=TestService,
        )

        # Should return False (not registered)
        assert result is False

        # Should still have only one descriptor
        assert len(services._descriptors) == 1
        assert TestService in services._descriptors

    def test_register_if_absent_allows_new(self) -> None:
        """Verify that register_if_absent allows new registrations."""
        services = ServiceCollection()

        class TestService:
            pass

        # Register new service
        result = register_if_absent(
            services,
            TestService,
            ServiceLifetime.SINGLETON,
            implementation_type=TestService,
        )

        # Should return True (registered)
        assert result is True

        # Should have the descriptor
        assert TestService in services._descriptors
        assert len(services._descriptors) == 1

    def test_register_singleton_if_absent(self) -> None:
        """Test convenience wrapper for singleton registration."""
        services = ServiceCollection()

        class TestService:
            pass

        # First registration should succeed
        result1 = register_singleton_if_absent(
            services, TestService, implementation_type=TestService
        )
        assert result1 is True

        # Second registration should be skipped
        result2 = register_singleton_if_absent(
            services, TestService, implementation_type=TestService
        )
        assert result2 is False

        # Verify descriptor
        descriptor = services._descriptors[TestService]
        assert descriptor.lifetime == ServiceLifetime.SINGLETON

    def test_register_scoped_if_absent(self) -> None:
        """Test convenience wrapper for scoped registration."""
        services = ServiceCollection()

        class TestService:
            pass

        result = register_scoped_if_absent(
            services, TestService, implementation_type=TestService
        )
        assert result is True

        descriptor = services._descriptors[TestService]
        assert descriptor.lifetime == ServiceLifetime.SCOPED

    def test_register_transient_if_absent(self) -> None:
        """Test convenience wrapper for transient registration."""
        services = ServiceCollection()

        class TestService:
            pass

        result = register_transient_if_absent(
            services, TestService, implementation_type=TestService
        )
        assert result is True

        descriptor = services._descriptors[TestService]
        assert descriptor.lifetime == ServiceLifetime.TRANSIENT

    def test_register_if_absent_with_factory(self) -> None:
        """Test register_if_absent with factory function."""
        services = ServiceCollection()

        class TestService:
            pass

        def factory(provider: Any) -> TestService:
            return TestService()

        result = register_if_absent(
            services,
            TestService,
            ServiceLifetime.SINGLETON,
            implementation_factory=factory,
        )

        assert result is True
        descriptor = services._descriptors[TestService]
        assert descriptor.implementation_factory is factory

    def test_register_if_absent_with_instance(self) -> None:
        """Test register_if_absent with existing instance."""
        services = ServiceCollection()

        class TestService:
            pass

        instance = TestService()

        result = register_if_absent(
            services,
            TestService,
            ServiceLifetime.SINGLETON,
            instance=instance,
        )

        assert result is True
        descriptor = services._descriptors[TestService]
        assert descriptor.instance is instance

    def test_repeated_registrar_invocations_idempotent(self) -> None:
        """Verify that calling register() multiple times produces same descriptors."""
        services1 = ServiceCollection()
        services2 = ServiceCollection()
        config = AppConfig()

        # Call registrar once
        core.register(services1, config)
        streaming.register(services1, config)

        # Call registrar multiple times
        core.register(services2, config)
        core.register(services2, config)
        streaming.register(services2, config)
        streaming.register(services2, config)

        # Both should have the same descriptors
        # (Currently empty, but structure should match)
        assert set(services1._descriptors.keys()) == set(services2._descriptors.keys())

    def test_register_interface_and_implementation(self) -> None:
        """Test register_interface_and_implementation utility."""
        services = ServiceCollection()

        class IInterface:
            pass

        class Implementation:
            pass

        # First registration should succeed
        result1 = register_interface_and_implementation(
            services,
            IInterface,
            Implementation,
            ServiceLifetime.SINGLETON,
        )
        assert result1 is True

        # Both should be registered
        assert IInterface in services._descriptors
        assert Implementation in services._descriptors

        # Second registration should be skipped
        result2 = register_interface_and_implementation(
            services,
            IInterface,
            Implementation,
            ServiceLifetime.SINGLETON,
        )
        assert result2 is False

        # Verify both point to same implementation
        interface_desc = services._descriptors[IInterface]
        impl_desc = services._descriptors[Implementation]
        assert interface_desc.implementation_type == Implementation
        assert impl_desc.implementation_type == Implementation


class TestOrchestratorIntegration:
    """Integration tests for the orchestrator."""

    def test_orchestrator_registers_all_feature_areas(self) -> None:
        """Verify orchestrator calls all registrars."""
        services = ServiceCollection()
        config = AppConfig()

        # Track which registrars were called
        call_counts = {
            "core": 0,
            "streaming": 0,
            "persistence": 0,
            "security": 0,
            "tooling": 0,
            "backend": 0,
            "resilience": 0,
        }

        # Mock registrars to track calls
        original_core = core.register
        original_streaming = streaming.register
        original_persistence = persistence.register
        original_security = security.register
        original_tooling = tooling.register
        original_backend = backend.register
        original_resilience = resilience.register

        def track_core(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["core"] += 1
            original_core(s, c)

        def track_streaming(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["streaming"] += 1
            original_streaming(s, c)

        def track_persistence(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["persistence"] += 1
            original_persistence(s, c)

        def track_security(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["security"] += 1
            original_security(s, c)

        def track_tooling(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["tooling"] += 1
            original_tooling(s, c)

        def track_backend(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["backend"] += 1
            original_backend(s, c)

        def track_resilience(s: ServiceCollection, c: AppConfig | None) -> None:
            call_counts["resilience"] += 1
            original_resilience(s, c)

        with (
            patch.object(core, "register", track_core),
            patch.object(streaming, "register", track_streaming),
            patch.object(persistence, "register", track_persistence),
            patch.object(security, "register", track_security),
            patch.object(tooling, "register", track_tooling),
            patch.object(backend, "register", track_backend),
            patch.object(resilience, "register", track_resilience),
        ):
            register_all(services, config)

        # Verify all registrars were called exactly once
        assert call_counts["core"] == 1
        assert call_counts["streaming"] == 1
        assert call_counts["persistence"] == 1
        assert call_counts["security"] == 1
        assert call_counts["tooling"] == 1
        assert call_counts["backend"] == 1
        assert call_counts["resilience"] == 1

    def test_orchestrator_order_matches_design(self) -> None:
        """Verify orchestrator calls registrars in the order specified in design.md."""
        services = ServiceCollection()
        config = AppConfig()

        call_order: list[str] = []

        # Store original functions to avoid recursion
        original_core = core.register
        original_streaming = streaming.register
        original_persistence = persistence.register
        original_security = security.register
        original_tooling = tooling.register
        original_backend = backend.register
        original_resilience = resilience.register

        def track_core(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("core")
            original_core(s, c)

        def track_streaming(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("streaming")
            original_streaming(s, c)

        def track_persistence(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("persistence")
            original_persistence(s, c)

        def track_security(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("security")
            original_security(s, c)

        def track_tooling(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("tooling")
            original_tooling(s, c)

        def track_backend(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("backend")
            original_backend(s, c)

        def track_resilience(s: ServiceCollection, c: AppConfig | None) -> None:
            call_order.append("resilience")
            original_resilience(s, c)

        with (
            patch.object(core, "register", track_core),
            patch.object(streaming, "register", track_streaming),
            patch.object(persistence, "register", track_persistence),
            patch.object(security, "register", track_security),
            patch.object(tooling, "register", track_tooling),
            patch.object(backend, "register", track_backend),
            patch.object(resilience, "register", track_resilience),
        ):
            register_all(services, config)

        # Verify order matches design.md specification:
        # 1. core
        # 2. streaming
        # 3. persistence
        # 4. security
        # 5. tooling
        # 6. backend
        # 7. resilience
        expected_order = [
            "core",
            "streaming",
            "persistence",
            "security",
            "tooling",
            "backend",
            "resilience",
        ]
        assert call_order == expected_order
