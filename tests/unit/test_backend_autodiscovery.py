"""
Tests for backend auto-discovery mechanism.

These tests verify that backends are automatically discovered and registered
without requiring hardcoded imports.
"""

import sys
from pathlib import Path

import pytest
from src.core.services.backend_registry import BackendRegistry


class TestBackendAutoDiscovery:
    """Test suite for backend auto-discovery functionality."""

    def test_all_backends_auto_registered(self):
        """Test that all backend modules are automatically discovered and registered."""
        # Create a fresh registry for testing
        test_registry = BackendRegistry()

        # Store the original global registry
        from src.core.services import backend_registry as registry_module

        original_registry = registry_module.backend_registry

        try:
            # Replace with test registry
            registry_module.backend_registry = test_registry

            # Remove connectors module from cache to force re-import
            modules_to_remove = [
                key for key in sys.modules if key.startswith("src.connectors")
            ]
            for module_name in modules_to_remove:
                del sys.modules[module_name]

            # Import connectors to trigger auto-discovery
            import src.connectors  # noqa: F401

            # Get all registered backends
            registered = test_registry.get_registered_backends()

            # Verify we have backends registered
            assert len(registered) > 0, "No backends were auto-discovered"

            # Expected backends (update this list as new backends are added)
            expected_backends = [
                "anthropic",
                "anthropic-oauth",
                "gemini",
                "gemini-cli-cloud-project",
                "gemini-cli-oauth-personal",
                "openai",
                "openai-oauth",
                "openrouter",
                "qwen-oauth",
                "zai",
                "zai-coding-plan",
            ]

            # Check that all expected backends are registered
            for backend_name in expected_backends:
                assert backend_name in registered, (
                    f"Backend '{backend_name}' was not auto-discovered. "
                    f"Registered backends: {registered}"
                )

            # Verify no duplicates
            assert len(registered) == len(
                set(registered)
            ), "Duplicate backends detected in registry"

        finally:
            # Restore original registry
            registry_module.backend_registry = original_registry

    def test_backend_modules_discovered_without_hardcoded_imports(self):
        """Test that backend modules are discovered dynamically, not from hardcoded list."""
        # Read the connectors __init__.py file
        connectors_init = Path("src/connectors/__init__.py")
        content = connectors_init.read_text()

        # Verify it uses pkgutil.iter_modules for discovery
        assert (
            "pkgutil.iter_modules" in content
        ), "Backend discovery should use pkgutil.iter_modules for auto-discovery"

        # Verify it doesn't have hardcoded backend imports (except base)
        # Check that we're not importing specific backends by name
        forbidden_patterns = [
            "from .anthropic import",
            "from .openai import",
            "from .gemini_oauth_personal import",
            "from .openrouter import",
        ]

        for pattern in forbidden_patterns:
            assert pattern not in content, (
                f"Found hardcoded import '{pattern}' in connectors __init__.py. "
                "Backends should be auto-discovered, not hardcoded."
            )

    def test_new_backend_would_be_auto_discovered(self, tmp_path):
        """Test that a new backend file would be automatically discovered."""
        # This test verifies the auto-discovery mechanism would work for new backends
        # by simulating the discovery process

        connectors_path = Path("src/connectors")

        # Get all Python files in connectors directory (excluding utilities)
        skip_files = ("__init__", "base", "streaming_utils", "gemini_request_counter")
        backend_files = [
            f.stem
            for f in connectors_path.glob("*.py")
            if f.stem not in skip_files and not f.stem.startswith("_")
        ]

        # Verify we found backend files
        assert len(backend_files) > 0, "No backend files found in src/connectors/"

        # Verify each backend file has register_backend call
        for backend_file in backend_files:
            backend_path = connectors_path / f"{backend_file}.py"
            content = backend_path.read_text()

            # Each backend should register itself
            assert "backend_registry.register_backend" in content, (
                f"Backend file '{backend_file}.py' doesn't call "
                "backend_registry.register_backend(). All backends must "
                "register themselves for auto-discovery to work."
            )

    def test_base_module_not_auto_imported(self):
        """Test that base.py is not auto-imported (it's imported explicitly)."""
        from src.core.services import backend_registry as registry_module

        test_registry = BackendRegistry()
        original_registry = registry_module.backend_registry

        try:
            registry_module.backend_registry = test_registry

            # Clear module cache
            modules_to_remove = [
                key for key in sys.modules if key.startswith("src.connectors")
            ]
            for module_name in modules_to_remove:
                del sys.modules[module_name]

            # Import connectors
            import src.connectors  # noqa: F401

            # base.py should not register any backend
            registered = test_registry.get_registered_backends()
            assert "base" not in registered, "base.py should not register a backend"

        finally:
            registry_module.backend_registry = original_registry

    def test_failed_backend_import_doesnt_break_others(self):
        """Test that if one backend fails to import, others still load."""
        # This is more of a documentation test showing the resilient behavior
        # The actual implementation logs warnings but continues

        connectors_init = Path("src/connectors/__init__.py")
        content = connectors_init.read_text()

        # Verify we have exception handling
        assert (
            "except Exception" in content
        ), "Auto-discovery should handle import failures gracefully"
        assert "logger.warning" in content, "Failed imports should be logged"

    def test_backend_registry_singleton_pattern(self):
        """Test that backend_registry is a singleton."""
        from src.core.services.backend_registry import backend_registry as reg1
        from src.core.services.backend_registry import backend_registry as reg2

        # Should be the same instance
        assert reg1 is reg2, "backend_registry should be a singleton"


class TestBackendRegistryInterface:
    """Test the BackendRegistry class interface."""

    def test_register_backend_basic(self):
        """Test basic backend registration."""
        registry = BackendRegistry()

        def mock_factory():
            pass

        registry.register_backend("test-backend", mock_factory)

        assert "test-backend" in registry.get_registered_backends()
        assert registry.get_backend_factory("test-backend") == mock_factory

    def test_register_backend_duplicate_logs_warning(self, caplog):
        """Test that registering a duplicate backend logs a warning."""
        registry = BackendRegistry()

        def mock_factory():
            pass

        registry.register_backend("test-backend", mock_factory)

        # Registering the same backend again should not raise an error but log a warning
        with caplog.at_level("WARNING"):
            registry.register_backend("test-backend", mock_factory)

        assert "already registered" in caplog.text
        # Verify it's still registered only once
        assert len(registry.get_registered_backends()) == 1

    def test_get_nonexistent_backend_raises_error(self):
        """Test that getting non-existent backend raises error."""
        registry = BackendRegistry()

        with pytest.raises(ValueError, match="not registered"):
            registry.get_backend_factory("nonexistent-backend")

    def test_register_backend_invalid_name_raises_error(self):
        """Test that invalid backend name raises error."""
        registry = BackendRegistry()

        def mock_factory():
            pass

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register_backend("", mock_factory)

        with pytest.raises(ValueError, match="non-empty string"):
            registry.register_backend(None, mock_factory)  # type: ignore

    def test_register_backend_invalid_factory_raises_error(self):
        """Test that invalid factory raises error."""
        registry = BackendRegistry()

        with pytest.raises(TypeError, match="must be a callable"):
            registry.register_backend("test-backend", "not-a-callable")  # type: ignore
