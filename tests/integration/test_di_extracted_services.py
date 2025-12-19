from unittest.mock import MagicMock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.model_alias_resolver_interface import IModelAliasResolver
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.services.backend_service import BackendService
from src.core.services.resilience import ResilienceCoordinator


class TestDIIntegration:
    def test_extracted_services_registration(self):
        """Verify that all new services are registered in the DI container."""
        collection = ServiceCollection()
        config = AppConfig()

        # Register dependencies required by some services
        collection.add_instance(BackendFactory, MagicMock(spec=BackendFactory))

        register_core_services(collection, config)
        provider = collection.build_service_provider()

        # Check resolution of all new interfaces
        assert provider.get_service(IStreamFormattingService) is not None
        assert provider.get_service(IUsageTrackingWrapper) is not None
        assert provider.get_service(IModelAliasResolver) is not None
        assert provider.get_service(IURIParameterApplicator) is not None
        assert provider.get_service(IReasoningConfigApplicator) is not None
        assert provider.get_service(IPlanningPhaseManager) is not None
        assert provider.get_service(IBackendLifecycleManager) is not None
        assert provider.get_service(IExceptionNormalizer) is not None

    def test_backend_service_injection(self):
        """Verify that BackendService receives all injected dependencies."""
        collection = ServiceCollection()

        # Register dependencies required by some services
        collection.add_instance(BackendFactory, MagicMock(spec=BackendFactory))
        collection.add_instance(
            IBackendConfigProvider, MagicMock(spec=IBackendConfigProvider)
        )
        collection.add_instance(IWireCapture, MagicMock(spec=IWireCapture))
        collection.add_instance(
            BackendRoutingService, MagicMock(spec=BackendRoutingService)
        )
        collection.add_instance(
            ResilienceCoordinator, MagicMock(spec=ResilienceCoordinator)
        )

        config = AppConfig()
        register_core_services(collection, config)
        provider = collection.build_service_provider()

        # All required services should be registered by register_core_services
        backend_service = provider.get_service(IBackendService)
        assert isinstance(backend_service, BackendService)

        # Verify internal attributes are populated (checking private attrs set in __init__)
        assert backend_service._stream_formatting_service is not None
        assert backend_service._usage_tracking_wrapper is not None
        assert backend_service._model_alias_resolver is not None
        assert backend_service._exception_normalizer is not None
        assert backend_service._backend_lifecycle_manager is not None
        assert backend_service._planning_phase_manager is not None
        assert backend_service._reasoning_config_applicator is not None
        assert backend_service._uri_parameter_applicator is not None
