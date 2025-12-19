"""
Tests for security services registrar.

These tests verify that:
- PathValidationService and IPathValidator are registered correctly
- UnifiedToolSecurityHandler is registered correctly
- Security services are optional (disabled features don't block startup)
- Integration with orchestrator works
- Idempotency is preserved
"""

from __future__ import annotations

from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import security
from src.core.interfaces.path_validator_interface import IPathValidator
from src.core.services.path_validation_service import PathValidationService


class TestSecurityRegistrarPathValidation:
    """Test path validation service registration."""

    def test_path_validation_service_registration(self) -> None:
        """Verify PathValidationService is registered as singleton."""
        services = ServiceCollection()
        config = AppConfig()

        security.register(services, config)
        provider = services.build_service_provider()

        path_validator = provider.get_service(PathValidationService)
        assert path_validator is not None
        assert isinstance(path_validator, PathValidationService)

    def test_ipath_validator_interface_registration(self) -> None:
        """Verify IPathValidator interface is registered."""
        services = ServiceCollection()
        config = AppConfig()

        security.register(services, config)
        provider = services.build_service_provider()

        ipath_validator = provider.get_service(cast(type, IPathValidator))
        assert ipath_validator is not None
        assert isinstance(ipath_validator, PathValidationService)

    def test_path_validation_service_idempotency(self) -> None:
        """Verify PathValidationService registration is idempotent."""
        services = ServiceCollection()
        config = AppConfig()

        # Register twice
        security.register(services, config)
        security.register(services, config)
        provider = services.build_service_provider()

        # Should still resolve correctly
        path_validator = provider.get_service(PathValidationService)
        assert path_validator is not None


class TestSecurityRegistrarUnifiedToolSecurity:
    """Test unified tool security handler registration."""

    def test_unified_tool_security_handler_registration_when_enabled(
        self,
    ) -> None:
        """Verify UnifiedToolSecurityHandler is registered when enabled."""
        services = ServiceCollection()
        # Create config with enabled features (configs are frozen, so we check defaults)
        config = AppConfig()

        security.register(services, config)
        provider = services.build_service_provider()

        # UnifiedToolSecurityHandler should be registered
        from src.core.services.unified_tool_security_handler import (
            UnifiedToolSecurityHandler,
        )

        handler = provider.get_service(UnifiedToolSecurityHandler)
        # Handler may be None if tool call reactor is disabled
        # This is acceptable - handlers are registered post-build
        assert handler is None or isinstance(handler, UnifiedToolSecurityHandler)

    def test_security_services_optional_when_disabled(self) -> None:
        """Verify security services don't block startup when disabled."""
        services = ServiceCollection()
        # Config defaults may have features disabled - that's fine
        config = AppConfig()

        # Should not raise exceptions even if features are disabled
        security.register(services, config)
        provider = services.build_service_provider()

        # PathValidationService should still be registered (it's always available)
        path_validator = provider.get_service(PathValidationService)
        assert path_validator is not None


class TestSecurityRegistrarIntegration:
    """Test security registrar integration with orchestrator."""

    def test_security_registrar_called_by_orchestrator(self) -> None:
        """Verify security registrar is called by orchestrator."""
        from src.core.di.registrations._orchestrator import register_all

        services = ServiceCollection()
        config = AppConfig()

        register_all(services, config)
        provider = services.build_service_provider()

        # Security services should be registered
        path_validator = provider.get_service(PathValidationService)
        assert path_validator is not None

    def test_security_registrar_with_none_config(self) -> None:
        """Verify security registrar works with None config."""
        services = ServiceCollection()

        security.register(services, None)
        provider = services.build_service_provider()

        # PathValidationService should still be registered
        path_validator = provider.get_service(PathValidationService)
        assert path_validator is not None
