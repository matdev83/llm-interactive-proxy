from __future__ import annotations

import importlib
import sys


def test_core_services_package_does_not_eagerly_import_service_exports() -> None:
    original_modules = sys.modules.copy()
    try:
        for key in list(sys.modules.keys()):
            if key == "src.core.services" or key.startswith("src.core.services."):
                sys.modules.pop(key, None)

        services = importlib.import_module("src.core.services")

        assert "src.core.services.auth_scope_resolver_service" not in sys.modules
        assert services.DefaultAuthScopeResolver.__name__ == "DefaultAuthScopeResolver"
    finally:
        sys.modules.update(original_modules)
        for key in list(sys.modules.keys()):
            if key not in original_modules:
                sys.modules.pop(key, None)


def test_backend_completion_flow_package_does_not_eagerly_import_flow_service() -> None:
    original_modules = sys.modules.copy()
    try:
        for key in list(sys.modules.keys()):
            if key == "src.core.services.backend_completion_flow" or key.startswith(
                "src.core.services.backend_completion_flow."
            ):
                sys.modules.pop(key, None)

        package = importlib.import_module("src.core.services.backend_completion_flow")

        assert "src.core.services.backend_completion_flow.service" not in sys.modules
        assert package.BackendCompletionFlow.__name__ == "BackendCompletionFlow"
    finally:
        sys.modules.update(original_modules)
        for key in list(sys.modules.keys()):
            if key not in original_modules:
                sys.modules.pop(key, None)


def test_connectors_package_does_not_eagerly_discover_all_connectors() -> None:
    original_modules = sys.modules.copy()
    try:
        for key in list(sys.modules.keys()):
            if key == "src.connectors" or key.startswith("src.connectors."):
                sys.modules.pop(key, None)

        connectors = importlib.import_module("src.connectors")

        assert "src.connectors.anthropic" not in sys.modules
        assert connectors.LLMBackend.__name__ == "LLMBackend"
    finally:
        sys.modules.update(original_modules)
        for key in list(sys.modules.keys()):
            if key not in original_modules:
                sys.modules.pop(key, None)
