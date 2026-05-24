"""Tests for BackendService extracted services registration."""

from collections.abc import Iterator

import pytest
from src.core.di.container import ServiceCollection
from src.core.di.services import (
    register_core_services,
    set_service_provider,
)
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
from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
from src.core.services.backend_service import BackendService
from src.core.services.exception_normalizer import ExceptionNormalizer
from src.core.services.model_alias_resolver import ModelAliasResolver
from src.core.services.planning_phase_manager import PlanningPhaseManager
from src.core.services.reasoning_config_applicator import ReasoningConfigApplicator
from src.core.services.stream_formatting_service import StreamFormattingService
from src.core.services.uri_parameter_applicator import URIParameterApplicator
from src.core.services.usage_tracking_wrapper import UsageTrackingWrapper


class TestBackendServiceRegistration:
    """Tests for BackendService and extracted services DI registration."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        """Reset service provider before/after tests."""
        set_service_provider(None)
        yield
        set_service_provider(None)

    def test_extracted_services_registration(self) -> None:
        """Verify all extracted services are registered as singletons."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # StreamFormattingService
        sfs1 = provider.get_required_service(IStreamFormattingService)
        sfs2 = provider.get_required_service(IStreamFormattingService)
        assert isinstance(sfs1, StreamFormattingService)
        assert sfs1 is sfs2

        # UsageTrackingWrapper
        utw1 = provider.get_required_service(IUsageTrackingWrapper)
        utw2 = provider.get_required_service(IUsageTrackingWrapper)
        assert isinstance(utw1, UsageTrackingWrapper)
        assert utw1 is utw2

        # ModelAliasResolver
        mar1 = provider.get_required_service(IModelAliasResolver)
        mar2 = provider.get_required_service(IModelAliasResolver)
        assert isinstance(mar1, ModelAliasResolver)
        assert mar1 is mar2

        # URIParameterApplicator
        upa1 = provider.get_required_service(IURIParameterApplicator)
        upa2 = provider.get_required_service(IURIParameterApplicator)
        assert isinstance(upa1, URIParameterApplicator)
        assert upa1 is upa2

        # ReasoningConfigApplicator
        rca1 = provider.get_required_service(IReasoningConfigApplicator)
        rca2 = provider.get_required_service(IReasoningConfigApplicator)
        assert isinstance(rca1, ReasoningConfigApplicator)
        assert rca1 is rca2

        # PlanningPhaseManager
        ppm1 = provider.get_required_service(IPlanningPhaseManager)
        ppm2 = provider.get_required_service(IPlanningPhaseManager)
        assert isinstance(ppm1, PlanningPhaseManager)
        assert ppm1 is ppm2

        # BackendLifecycleManager
        blm1 = provider.get_required_service(IBackendLifecycleManager)
        blm2 = provider.get_required_service(IBackendLifecycleManager)
        assert isinstance(blm1, BackendLifecycleManager)
        assert blm1 is blm2

        # ExceptionNormalizer
        en1 = provider.get_required_service(IExceptionNormalizer)
        en2 = provider.get_required_service(IExceptionNormalizer)
        assert isinstance(en1, ExceptionNormalizer)
        assert en1 is en2

    def test_backend_service_injection(self) -> None:
        """Verify BackendService receives injected services."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Resolve BackendService
        backend_service = provider.get_required_service(IBackendService)
        assert isinstance(backend_service, BackendService)

        # Check that dependencies were injected
        # Note: We access private attributes here to verify injection
        assert isinstance(
            backend_service._stream_formatting_service, StreamFormattingService
        )
        assert isinstance(backend_service._usage_tracking_wrapper, UsageTrackingWrapper)
        assert isinstance(backend_service._model_alias_resolver, ModelAliasResolver)
        assert isinstance(
            backend_service._uri_parameter_applicator, URIParameterApplicator
        )
        assert isinstance(
            backend_service._reasoning_config_applicator, ReasoningConfigApplicator
        )
        assert isinstance(backend_service._planning_phase_manager, PlanningPhaseManager)
        assert isinstance(
            backend_service._backend_lifecycle_manager, BackendLifecycleManager
        )
        assert isinstance(backend_service._exception_normalizer, ExceptionNormalizer)
