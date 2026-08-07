"""
Regression tests for BackendService DI and initialization issues.

These tests ensure that critical services meant to be registered in the DI container
are present, and that the BackendService factory correctly treats certain dependencies
as optional.
"""

from unittest.mock import MagicMock, Mock

import pytest
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_config_provider import BackendConfigProvider
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry
from src.core.services.backend_service import BackendService


class TestBackendServiceDIRegression:
    def test_backend_core_dependencies_are_registered(self) -> None:
        """
        Regression test for ensuring BackendRegistry, BackendFactory, and BackendConfigProvider
        are correctly registered in the DI container.

        Ref: Fix for ServiceResolutionError in step 663.
        """
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # 1. Verify BackendRegistry registration
        registry = provider.get_service(BackendRegistry)
        assert registry is not None, "BackendRegistry should be registered"
        assert isinstance(registry, BackendRegistry)

        # 2. Verify BackendFactory registration
        factory = provider.get_service(BackendFactory)
        assert factory is not None, "BackendFactory should be registered"
        # We might check for the interface too if it was registered that way
        # In the fix, we registered both concrete and implicit interface usage by consumers

        # 3. Verify BackendConfigProvider registration
        config_provider = provider.get_service(BackendConfigProvider)
        assert config_provider is not None, "BackendConfigProvider should be registered"
        assert isinstance(config_provider, BackendConfigProvider)

        # 4. Verify IBackendConfigProvider interface resolution
        # Attempts to resolve the interface should return the concrete type
        interface_provider = provider.get_service(IBackendConfigProvider)
        assert (
            interface_provider is not None
        ), "IBackendConfigProvider should be registered"
        assert isinstance(interface_provider, BackendConfigProvider)

    def test_backend_service_factory_treats_wire_capture_as_optional(self) -> None:
        """
        Regression test for ensuring IWireCapture is treated as an optional dependency
        in the BackendService factory.

        Ref: Fix for ServiceResolutionError in step 660 where IWireCapture was missing.
        """
        services = ServiceCollection()
        register_core_services(services)

        # Find the BackendService descriptor to get its factory
        descriptor = next(
            (
                d
                for d in services._descriptors.values()
                if d.service_type is BackendService
            ),
            None,
        )
        assert descriptor is not None, "BackendService descriptor not found"
        assert (
            descriptor.implementation_factory is not None
        ), "BackendService must have a factory"

        # Create a mock provider that enforces the 'optional' contract
        mock_provider = Mock(spec=IServiceProvider)

        # Setup specific behavior:
        # 1. get_required_service(IWireCapture) MUST raise an error (simulating it's not there)
        # 2. get_service(IWireCapture) MUST return None (simulating it's missing but allowed)

        def get_required_side_effect(service_type):
            if service_type is IWireCapture:
                raise Exception(
                    "REGRESSION: BackendService tried to require IWireCapture!"
                )
            # For other services, return mocks
            return MagicMock()

        mock_provider.get_required_service.side_effect = get_required_side_effect

        def get_service_side_effect(service_type):
            if service_type is IWireCapture:
                return None
            return MagicMock()

        mock_provider.get_service.side_effect = get_service_side_effect

        # We need to ensure AppConfig is returned as an AppConfig object so
        # validation logic inside the factory doesn't crash on attribute access
        mock_config = MagicMock(spec=AppConfig)
        # Configure minimal attributes needed by BackendService.__init__
        mock_config.session = MagicMock()
        mock_config.session.max_per_session_backends = 10
        mock_config.failures = MagicMock()

        # Refine get_required_service to return typed mocks where necessary
        def refined_get_required_service(service_type):
            if service_type is IWireCapture:
                raise Exception(
                    "REGRESSION: BackendService tried to require IWireCapture!"
                )
            if service_type is AppConfig:
                return mock_config
            return MagicMock()

        mock_provider.get_required_service.side_effect = refined_get_required_service

        # Attempt to create the service using the factory
        # If the code uses get_required_service(IWireCapture), this will raise our specific exception
        try:
            backend_service = descriptor.implementation_factory(mock_provider)
        except Exception as e:
            if "REGRESSION:" in str(e):
                pytest.fail(str(e))
            raise

        assert backend_service is not None
        # Verify internal state reflects optionality
        assert backend_service._wire_capture is None
