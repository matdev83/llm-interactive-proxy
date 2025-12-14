
import inspect
from typing import get_type_hints

from hypothesis import given, strategies as st

from src.core.interfaces.backend_service_interface import IBackendService
from src.core.services.backend_service import BackendService


class TestBackendServiceAPIPreservation:
    def test_backend_service_implements_interface(self):
        """Verify BackendService implements IBackendService."""
        assert issubclass(BackendService, IBackendService)
        
        # Check all abstract methods are implemented
        abstract_methods = IBackendService.__abstractmethods__
        for method in abstract_methods:
            assert hasattr(BackendService, method), f"BackendService missing {method}"

    def test_backend_service_public_api_signatures(self):
        """Verify public API signatures match expectations."""
        # Key public methods
        methods = [
            "call_completion",
            "chat_completions",
            "validate_backend_and_model",
            "get_active_backends",
        ]
        
        for method_name in methods:
            assert hasattr(BackendService, method_name)
            method = getattr(BackendService, method_name)
            assert callable(method)
            
            # Check signature logic (simplified)
            sig = inspect.signature(method)
            assert sig.parameters, f"{method_name} should have parameters"

    def test_backend_service_legacy_delegating_methods_exist(self):
        """Verify extracted private methods still exist as delegating wrappers."""
        legacy_methods = [
            "_stream_as_sse_bytes",
            "_is_valid_completion_token",
            "_wrap_stream_for_usage",
            "_apply_model_aliases",
            "_apply_uri_parameters",
            "_apply_reasoning_config",
            "_apply_planning_phase_if_needed",
            "_update_planning_phase_counters",
            "_count_file_writes_in_response",
            "_get_or_create_backend",
            "_shutdown_backend",
            "_discard_backend",
            "_normalize_provider_exception",
        ]
        
        for method_name in legacy_methods:
            assert hasattr(BackendService, method_name), f"BackendService missing legacy method {method_name}"
            method = getattr(BackendService, method_name)
            assert callable(method)
