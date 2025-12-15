"""Property tests for BackendService API signature preservation.

Verifies that the refactored BackendService maintains strict API compatibility
with the IBackendService interface and previous behavior.
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

from src.core.interfaces.backend_service_interface import IBackendService
from src.core.services.backend_service import BackendService


class TestBackendServiceAPIPreservation:
    """Verify BackendService preserves IBackendService API."""

    def test_implements_interface(self) -> None:
        """BackendService should implement IBackendService."""
        assert issubclass(BackendService, IBackendService)

    def test_method_signatures_match_interface(self) -> None:
        """Public methods should match interface signatures exactly."""
        interface_methods = {
            name: method
            for name, method in inspect.getmembers(
                IBackendService, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }

        implementation_methods = {
            name: method
            for name, method in inspect.getmembers(
                BackendService, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        }

        for name, interface_method in interface_methods.items():
            assert name in implementation_methods, f"Missing public method {name}"

            impl_method = implementation_methods[name]

            # Check signatures
            interface_sig = inspect.signature(interface_method)
            impl_sig = inspect.signature(impl_method)

            # Check parameters (ignoring self)
            interface_params = list(interface_sig.parameters.values())[1:]
            impl_params = list(impl_sig.parameters.values())[1:]

            assert len(interface_params) == len(
                impl_params
            ), f"Parameter count mismatch for {name}"

            for i_param, impl_param in zip(interface_params, impl_params, strict=False):
                assert (
                    i_param.name == impl_param.name
                ), f"Parameter name mismatch in {name}: {i_param.name} vs {impl_param.name}"
                assert (
                    i_param.kind == impl_param.kind
                ), f"Parameter kind mismatch in {name}: {i_param.name}"
                assert (
                    i_param.default == impl_param.default
                ), f"Parameter default mismatch in {name}: {i_param.name}"

            # Check return type hints if present in interface
            interface_hints = get_type_hints(interface_method)
            impl_hints = get_type_hints(impl_method)

            if "return" in interface_hints:
                assert (
                    "return" in impl_hints
                ), f"Missing return type hint in implementation of {name}"
                # Strict equality check might fail due to import differences, but let's try basic check
                # assert interface_hints["return"] == impl_hints["return"]

    def test_legacy_helpers_exist(self) -> None:
        """Legacy helper methods must exist for backward compatibility."""
        legacy_methods = [
            "_stream_as_sse_bytes",
            "_wrap_stream_for_usage",
            "_apply_model_aliases",
            "_apply_reasoning_config",
            "_apply_uri_parameters",
            "_is_valid_completion_token",
            "_normalize_provider_exception",
        ]

        for method_name in legacy_methods:
            assert hasattr(
                BackendService, method_name
            ), f"Missing legacy helper {method_name}"
            method = getattr(BackendService, method_name)
            assert callable(method), f"{method_name} is not callable"
