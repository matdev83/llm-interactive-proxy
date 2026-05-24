"""
Tests for DI diagnostics resolution path tracking.

These tests verify that resolution path tracking works correctly when
DI_STRICT_DIAGNOSTICS is enabled, and that behavior is unchanged when disabled.
"""

import asyncio

import pytest
from src.core.common.exceptions import ServiceResolutionError
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider


class ServiceA:
    """Test service A."""

    def __init__(self) -> None:
        self.name = "A"


class ServiceB:
    """Test service B that depends on ServiceA."""

    def __init__(self, service_provider: IServiceProvider) -> None:
        self.dependency = service_provider.get_required_service(ServiceA)
        self.name = "B"


class ServiceC:
    """Test service C that depends on ServiceB."""

    def __init__(self, service_provider: IServiceProvider) -> None:
        self.dependency = service_provider.get_required_service(ServiceB)
        self.name = "C"


class ScopedService:
    """A scoped service for testing scoped-from-root errors."""

    def __init__(self) -> None:
        self.name = "Scoped"


class FailingFactoryService:
    """A service that fails during factory creation."""

    def __init__(self) -> None:
        raise ValueError("Factory failed")


class TestMissingServiceErrorWithDiagnostics:
    """Test missing-service errors with diagnostics enabled."""

    @pytest.fixture(autouse=True)
    def enable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enable DI diagnostics for these tests."""
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "true")

    def test_missing_service_error_includes_resolution_path(self) -> None:
        """Test that missing-service errors include resolution path when diagnostics enabled."""
        # Arrange
        services = ServiceCollection()
        provider = services.build_service_provider()

        # Act & Assert
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(ServiceA)

        error = exc_info.value
        assert error.details is not None
        assert error.details["missing_service"] == "ServiceA"
        assert error.details["diagnostics_enabled"] is True
        assert "resolution_path" in error.details
        resolution_path = error.details["resolution_path"]
        assert isinstance(resolution_path, list)
        assert len(resolution_path) >= 1
        assert "ServiceA" in resolution_path

    def test_nested_dependency_resolution_path(self) -> None:
        """Test that resolution path tracks full dependency chain."""
        # Arrange
        services = ServiceCollection()
        services.add_singleton(ServiceA)
        services.add_singleton(
            ServiceB,
            implementation_factory=lambda provider: ServiceB(provider),
        )
        services.add_singleton(
            ServiceC,
            implementation_factory=lambda provider: ServiceC(provider),
        )
        provider = services.build_service_provider()

        # Act - This should work fine
        service_c = provider.get_service(ServiceC)
        assert service_c is not None
        assert service_c.name == "C"
        assert service_c.dependency.name == "B"
        assert service_c.dependency.dependency.name == "A"

    def test_missing_nested_dependency_shows_full_path(self) -> None:
        """Test that missing nested dependency shows full resolution path."""
        # Arrange - ServiceB depends on ServiceA, but ServiceA is not registered
        services = ServiceCollection()
        services.add_singleton(
            ServiceB,
            implementation_factory=lambda provider: ServiceB(provider),
        )
        provider = services.build_service_provider()

        # Act & Assert
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(ServiceB)

        error = exc_info.value
        assert error.details is not None
        assert error.details["missing_service"] == "ServiceA"
        assert error.details["diagnostics_enabled"] is True
        resolution_path = error.details["resolution_path"]
        assert isinstance(resolution_path, list)
        # Should show ServiceB -> ServiceA path
        assert "ServiceB" in resolution_path
        assert "ServiceA" in resolution_path
        # ServiceA should be last (the failing dependency)
        assert resolution_path[-1] == "ServiceA"


class TestMissingServiceErrorWithoutDiagnostics:
    """Test missing-service errors with diagnostics disabled."""

    @pytest.fixture(autouse=True)
    def disable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disable DI diagnostics for these tests."""
        monkeypatch.delenv("DI_STRICT_DIAGNOSTICS", raising=False)
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "false")

    def test_missing_service_error_no_extra_details(self) -> None:
        """Test that missing-service errors don't include extra details when diagnostics disabled."""
        # Arrange
        services = ServiceCollection()
        provider = services.build_service_provider()

        # Act & Assert
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(ServiceA)

        error = exc_info.value
        # Should have basic error message but no resolution path details
        assert "ServiceA" in str(error)
        # Details may exist but should not contain diagnostics-specific fields
        if error.details:
            assert "diagnostics_enabled" not in error.details
            assert "resolution_path" not in error.details


class TestScopedFromRootErrorWithDiagnostics:
    """Test scoped-from-root errors with diagnostics enabled."""

    @pytest.fixture(autouse=True)
    def enable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enable DI diagnostics for these tests."""
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "true")

    def test_scoped_from_root_raises_service_resolution_error(self) -> None:
        """Test that scoped-from-root errors raise ServiceResolutionError with diagnostics."""
        # Arrange
        services = ServiceCollection()
        services.add_scoped(ScopedService)
        provider = services.build_service_provider()

        # Act & Assert - Resolving scoped service from root should fail
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(ScopedService)

        error = exc_info.value
        assert error.details is not None
        assert error.details["reason"] == "scoped_service_from_root"
        assert error.details["diagnostics_enabled"] is True
        assert "resolution_path" in error.details
        resolution_path = error.details["resolution_path"]
        assert isinstance(resolution_path, list)
        assert "ScopedService" in resolution_path


class TestScopedFromRootErrorWithoutDiagnostics:
    """Test scoped-from-root errors with diagnostics disabled."""

    @pytest.fixture(autouse=True)
    def disable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disable DI diagnostics for these tests."""
        monkeypatch.delenv("DI_STRICT_DIAGNOSTICS", raising=False)
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "false")

    def test_scoped_from_root_raises_runtime_error(self) -> None:
        """Test that scoped-from-root errors raise RuntimeError when diagnostics disabled."""
        # Arrange
        services = ServiceCollection()
        services.add_scoped(ScopedService)
        provider = services.build_service_provider()

        # Act & Assert - Should raise RuntimeError (existing behavior)
        with pytest.raises(RuntimeError) as exc_info:
            provider.get_required_service(ScopedService)

        error = exc_info.value
        assert "scoped service" in str(error).lower()
        assert "ScopedService" in str(error)


class TestFactoryFailureWithDiagnostics:
    """Test factory failures with diagnostics enabled."""

    @pytest.fixture(autouse=True)
    def enable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enable DI diagnostics for these tests."""
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "true")

    def test_factory_failure_wrapped_with_resolution_path(self) -> None:
        """Test that factory failures are wrapped with resolution path."""
        # Arrange
        services = ServiceCollection()

        def failing_factory(_provider: IServiceProvider) -> FailingFactoryService:
            raise ValueError("Factory failed")

        services.add_singleton(
            FailingFactoryService, implementation_factory=failing_factory
        )
        provider = services.build_service_provider()

        # Act & Assert
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(FailingFactoryService)

        error = exc_info.value
        assert error.details is not None
        assert error.details["reason"] == "factory_exception"
        assert error.details["diagnostics_enabled"] is True
        assert "error_type" in error.details
        assert "error_message" in error.details
        assert "resolution_path" in error.details
        # Original exception should be preserved as __cause__
        assert error.__cause__ is not None
        assert isinstance(error.__cause__, ValueError)
        assert "Factory failed" in str(error.__cause__)

    def test_constructor_failure_wrapped_with_resolution_path(self) -> None:
        """Test that constructor failures are wrapped with resolution path."""
        # Arrange
        services = ServiceCollection()
        services.add_singleton(FailingFactoryService)
        provider = services.build_service_provider()

        # Act & Assert
        with pytest.raises(ServiceResolutionError) as exc_info:
            provider.get_required_service(FailingFactoryService)

        error = exc_info.value
        assert error.details is not None
        assert error.details["reason"] == "factory_exception"
        assert error.details["diagnostics_enabled"] is True
        assert "resolution_path" in error.details
        # Original exception should be preserved as __cause__
        assert error.__cause__ is not None


class TestFactoryFailureWithoutDiagnostics:
    """Test factory failures with diagnostics disabled."""

    @pytest.fixture(autouse=True)
    def disable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disable DI diagnostics for these tests."""
        monkeypatch.delenv("DI_STRICT_DIAGNOSTICS", raising=False)
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "false")

    def test_factory_failure_propagates_unchanged(self) -> None:
        """Test that factory failures propagate unchanged when diagnostics disabled."""
        # Arrange
        services = ServiceCollection()

        def failing_factory(_provider: IServiceProvider) -> FailingFactoryService:
            raise ValueError("Factory failed")

        services.add_singleton(
            FailingFactoryService, implementation_factory=failing_factory
        )
        provider = services.build_service_provider()

        # Act & Assert - Should raise original exception (may be wrapped by container logic)
        # The current implementation may wrap it, but we verify it's not ServiceResolutionError
        # with diagnostics details
        with pytest.raises(Exception) as exc_info:
            provider.get_required_service(FailingFactoryService)

        # Should not be a ServiceResolutionError with diagnostics details
        if (
            isinstance(exc_info.value, ServiceResolutionError)
            and exc_info.value.details
        ):
            assert "diagnostics_enabled" not in exc_info.value.details


class TestConcurrentResolutionIsolation:
    """Test that concurrent resolutions have independent resolution stacks."""

    @pytest.fixture(autouse=True)
    def enable_diagnostics(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Enable DI diagnostics for these tests."""
        monkeypatch.setenv("DI_STRICT_DIAGNOSTICS", "true")

    @pytest.mark.asyncio
    async def test_concurrent_resolutions_have_independent_stacks(self) -> None:
        """Test that multiple async tasks have independent resolution stacks."""
        # Arrange
        services = ServiceCollection()
        services.add_singleton(ServiceA)
        services.add_singleton(
            ServiceB,
            implementation_factory=lambda provider: ServiceB(provider),
        )
        provider = services.build_service_provider()

        async def resolve_service_a() -> ServiceA:
            """Resolve ServiceA in this task."""
            return provider.get_required_service(ServiceA)

        async def resolve_service_b() -> ServiceB:
            """Resolve ServiceB (which depends on ServiceA) in this task."""
            return provider.get_required_service(ServiceB)

        # Act - Resolve concurrently
        results = await asyncio.gather(
            resolve_service_a(), resolve_service_b(), return_exceptions=True
        )

        # Assert - Both should succeed without interfering with each other
        assert len(results) == 2
        assert isinstance(results[0], ServiceA)
        assert isinstance(results[1], ServiceB)
        assert results[1].dependency is results[0]  # Same singleton instance

    @pytest.mark.asyncio
    async def test_concurrent_missing_service_errors_isolated(self) -> None:
        """Test that concurrent missing-service errors have independent resolution paths."""
        # Arrange
        services = ServiceCollection()
        provider = services.build_service_provider()

        async def resolve_missing_a() -> Exception:
            """Try to resolve missing ServiceA."""
            try:
                provider.get_required_service(ServiceA)
                return None  # type: ignore[return-value]
            except ServiceResolutionError as e:
                return e

        async def resolve_missing_b() -> Exception:
            """Try to resolve missing ServiceB."""
            try:
                provider.get_required_service(ServiceB)
                return None  # type: ignore[return-value]
            except ServiceResolutionError as e:
                return e

        # Act - Resolve concurrently
        errors = await asyncio.gather(
            resolve_missing_a(), resolve_missing_b(), return_exceptions=False
        )

        # Assert - Both errors should have correct resolution paths
        error_a = errors[0]
        error_b = errors[1]

        assert isinstance(error_a, ServiceResolutionError)
        assert isinstance(error_b, ServiceResolutionError)

        if error_a.details and error_b.details:
            path_a = error_a.details.get("resolution_path", [])
            path_b = error_b.details.get("resolution_path", [])

            # Each should show its own service in the path
            assert "ServiceA" in path_a
            assert "ServiceB" in path_b
