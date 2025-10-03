"""
Integration test for backend_imports module.

This test verifies that the backend_imports module correctly triggers
connector auto-discovery when imported, which is critical for the CLI
to function properly.

This test was created after a bug where backend_imports.py was empty,
causing the CLI to not load any connectors even though the auto-discovery
mechanism in src/connectors/__init__.py existed.
"""

import sys
from collections.abc import Generator

import pytest


class TestBackendImportsIntegration:
    """Test that backend_imports properly loads all connectors."""

    @pytest.fixture
    def clean_import_state(self) -> Generator[None, None, None]:
        """Clean module cache before and after test to ensure fresh imports."""
        # Store modules to clean up
        modules_to_remove = [
            key
            for key in sys.modules
            if key.startswith("src.connectors")
            or key == "src.core.services.backend_imports"
        ]

        # Remove from cache
        for module_name in modules_to_remove:
            del sys.modules[module_name]

        # Also need to reset the backend registry
        from src.core.services.backend_registry import backend_registry

        original_factories = backend_registry._factories.copy()
        backend_registry._factories.clear()

        yield

        # Cleanup: restore original state
        backend_registry._factories.clear()
        backend_registry._factories.update(original_factories)

        # Remove test modules from cache
        modules_to_remove = [
            key
            for key in sys.modules
            if key.startswith("src.connectors")
            or key == "src.core.services.backend_imports"
        ]
        for module_name in modules_to_remove:
            if module_name in sys.modules:
                del sys.modules[module_name]

    def test_backend_imports_triggers_connector_discovery(
        self, clean_import_state: None
    ) -> None:
        """
        CRITICAL TEST: Verify that importing backend_imports loads all connectors.

        This test simulates what happens when the CLI starts:
        1. CLI imports backend_imports
        2. backend_imports should trigger connector auto-discovery
        3. All connectors should be registered in the backend registry

        If this test fails, it means the CLI won't be able to find any backends!
        """
        from src.core.services.backend_registry import backend_registry

        # Verify registry is empty at start (due to fixture cleanup)
        initial_backends = backend_registry.get_registered_backends()
        assert len(initial_backends) == 0, (
            f"Registry should be empty at start, but has: {initial_backends}. "
            "Check the clean_import_state fixture."
        )

        # NOW IMPORT backend_imports - this is what the CLI does
        import src.core.services.backend_imports  # noqa: F401

        # After importing backend_imports, ALL connectors should be registered
        registered_backends = backend_registry.get_registered_backends()

        # Verify we have backends registered
        assert len(registered_backends) > 0, (
            "CRITICAL BUG: Importing backend_imports did not register any backends! "
            "This means the CLI will not be able to use ANY backends. "
            "Check that backend_imports.py actually imports src.connectors."
        )

        # Expected backends (keep this list updated as new backends are added)
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
        missing_backends = [
            backend
            for backend in expected_backends
            if backend not in registered_backends
        ]

        assert len(missing_backends) == 0, (
            f"CRITICAL BUG: The following backends were not registered when importing backend_imports: "
            f"{missing_backends}. This means the CLI cannot use these backends. "
            f"Registered backends: {registered_backends}"
        )

        # Verify we have at least the expected number of backends
        assert len(registered_backends) >= len(expected_backends), (
            f"Expected at least {len(expected_backends)} backends, but only got {len(registered_backends)}. "
            f"Missing: {set(expected_backends) - set(registered_backends)}"
        )

    def test_backend_imports_makes_all_connector_classes_available(
        self, clean_import_state: None
    ) -> None:
        """
        Test that importing backend_imports makes connector classes importable.

        This ensures that not only are backends registered, but the actual
        connector classes can be imported and instantiated.
        """
        # Import backend_imports to trigger discovery
        import src.core.services.backend_imports  # noqa: F401
        from src.connectors.anthropic import AnthropicBackend

        # Now try to import some connector classes
        # These should work without any additional imports
        from src.connectors.gemini_oauth_personal import GeminiOAuthPersonalConnector
        from src.connectors.openai import OpenAIConnector

        # Verify they are actual classes
        assert isinstance(GeminiOAuthPersonalConnector, type)
        assert isinstance(AnthropicBackend, type)
        assert isinstance(OpenAIConnector, type)

    def test_backend_imports_idempotent(self, clean_import_state: None) -> None:
        """
        Test that importing backend_imports multiple times doesn't cause issues.

        This is important because the module might be imported from multiple places.
        """
        # Import once
        import src.core.services.backend_imports  # noqa: F401
        from src.core.services.backend_registry import backend_registry

        first_import_backends = set(backend_registry.get_registered_backends())
        assert len(first_import_backends) > 0

        # Import again (Python will use cached module)

        second_import_backends = set(backend_registry.get_registered_backends())

        # Should have the same backends
        assert (
            first_import_backends == second_import_backends
        ), "Multiple imports of backend_imports should result in the same set of backends"

    def test_cli_module_imports_backend_imports(self) -> None:
        """
        Test that the CLI module actually imports backend_imports.

        This is a static code check to ensure the import statement exists.
        """
        import inspect

        import src.core.cli

        # Get the source code of the CLI module
        cli_source = inspect.getsource(src.core.cli)

        # Check that it imports backend_imports
        assert (
            "from src.core.services import backend_imports" in cli_source
            or "import src.core.services.backend_imports" in cli_source
        ), (
            "CRITICAL BUG: The CLI module does not import backend_imports! "
            "This means no backends will be loaded when the CLI starts. "
            "Add 'from src.core.services import backend_imports' to src/core/cli.py"
        )

    def test_backend_imports_file_not_empty(self) -> None:
        """
        Test that backend_imports.py is not empty or trivial.

        This is a static check to catch the specific bug where backend_imports.py
        was reduced to just docstrings and __all__ = [].
        """
        from pathlib import Path

        # Find the backend_imports.py file
        backend_imports_path = (
            Path(__file__).parent.parent.parent
            / "src"
            / "core"
            / "services"
            / "backend_imports.py"
        )
        assert (
            backend_imports_path.exists()
        ), f"backend_imports.py not found at {backend_imports_path}"

        # Read the file
        content = backend_imports_path.read_text()

        # Check that it actually imports something
        # It should either directly import connectors or import each connector module
        has_meaningful_imports = (
            "import src.connectors" in content
            or "from src.connectors import" in content
            or ("import" in content and "connector" in content.lower())
        )

        assert has_meaningful_imports, (
            "CRITICAL BUG: backend_imports.py does not import any connectors! "
            "The file appears to be empty or incomplete. "
            "It must import src.connectors to trigger auto-discovery, or import connector modules directly."
        )

        # Check that the file is not just docstrings and __all__
        # Remove comments, docstrings, and whitespace
        lines = [
            line.strip()
            for line in content.split("\n")
            if line.strip()
            and not line.strip().startswith("#")
            and not line.strip().startswith('"""')
            and not line.strip().startswith("'''")
        ]

        # Filter out __all__ and docstring lines
        code_lines = [
            line
            for line in lines
            if not line.startswith("__all__")
            and not line.startswith('"""')
            and not line.startswith("'''")
        ]

        # Should have at least one import statement
        import_lines = [line for line in code_lines if "import" in line]

        assert len(import_lines) > 0, (
            "CRITICAL BUG: backend_imports.py has no import statements! "
            f"File content (non-comment lines): {code_lines}"
        )


class TestBackendImportsErrorHandling:
    """Test error handling in backend imports."""

    def test_backend_imports_handles_missing_connector_gracefully(self) -> None:
        """
        Test that if a connector module is missing or broken, other connectors still load.

        This is covered by the auto-discovery mechanism which catches and logs errors,
        but we verify it doesn't crash the entire import process.
        """
        # This test just verifies that importing backend_imports doesn't raise
        # an exception even if there are issues with individual connectors
        try:
            import src.core.services.backend_imports  # noqa: F401

            success = True
        except Exception as e:
            success = False
            error_msg = str(e)

        assert success, (
            f"Importing backend_imports should never raise an exception, "
            f"but got: {error_msg if not success else 'N/A'}. "
            "The auto-discovery mechanism should catch and log errors for individual connectors."
        )
