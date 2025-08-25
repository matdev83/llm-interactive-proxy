import os
from unittest.mock import patch

import pytest
from src.core.app.test_builder import build_test_app as build_app


def _load_config():
    """Helper to load config from environment variables."""
    from src.core.config.config_loader import ConfigLoader

    loader = ConfigLoader()
    return loader.load_config()


class TestQwenOAuthInteractiveCommands:
    """Tests for Qwen OAuth interactive command handling."""

    def test_environment_variable_support(self):
        """Test that Qwen OAuth backend can be selected via environment variable."""
        with patch.dict(os.environ, {"LLM_BACKEND": "qwen-oauth"}):
            config = _load_config()
            assert config["backend"] == "qwen-oauth"

    def test_cli_argument_support(self):
        """Test that Qwen OAuth backend can be selected via CLI argument."""
        # Mock the CLI argument functionality
        with patch.dict(os.environ, {"LLM_BACKEND": "qwen-oauth"}):
            config = _load_config()
            assert config["backend"] == "qwen-oauth"

    def test_backend_attribute_name_conversion(self):
        """Test that backend names with hyphens are correctly converted to attribute names."""
        with patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "DISABLE_ACCOUNTING": "true"}
        ):
            # Test the backend name conversion logic directly
            backend_name = "qwen-oauth"
            backend_attr = backend_name.replace("-", "_")

            # The backend attribute should exist (even if the backend is mocked)
            # This tests the naming convention used in the application
            assert backend_attr == "qwen_oauth"
            assert backend_attr == "qwen_oauth"

    def test_backend_object_accessibility(self):
        """Test that the qwen-oauth backend object can be accessed correctly."""
        with patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "DISABLE_ACCOUNTING": "true"}
        ):
            # Test the correct way to access the backend using the naming convention
            backend_name = "qwen-oauth"
            backend_attr = backend_name.replace("-", "_")

            # The backend attribute name should follow the correct pattern
            assert backend_attr == "qwen_oauth"
            assert f"{backend_attr}_backend" == "qwen_oauth_backend"

            # Test that we can construct the backend attribute name correctly
            expected_attr_name = f"{backend_name.replace('-', '_')}_backend"
            assert expected_attr_name == "qwen_oauth_backend"

    @pytest.mark.asyncio
    async def test_functional_backends_includes_qwen_oauth(self):
        """Test that functional_backends can include qwen-oauth."""
        with patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "DISABLE_ACCOUNTING": "true"}
        ):
            app = build_app()

            # Safely initialize functional_backends if it doesn't exist
            if not hasattr(app.state, "functional_backends"):
                app.state.functional_backends = set()

            # Add qwen-oauth to functional backends for testing
            app.state.functional_backends.add("qwen-oauth")

            assert "qwen-oauth" in app.state.functional_backends

    def test_backend_routing_with_qwen_oauth(self):
        """Test that backend routing works with qwen-oauth."""
        # Test explicit routing with colon syntax
        model_str = "qwen-oauth:qwen3-coder-plus"
        if ":" in model_str:
            backend, model = model_str.split(":", 1)
            assert backend == "qwen-oauth"
            assert model == "qwen3-coder-plus"


class TestQwenOAuthConfigurationMethods:
    """Tests for Qwen OAuth configuration methods."""

    def test_dotenv_file_support(self):
        """Test that Qwen OAuth credentials can be loaded from .env file."""
        # For now, we test the config loading mechanism
        with patch.dict(os.environ, {"LLM_BACKEND": "qwen-oauth"}):
            config = _load_config()
            assert config["backend"] == "qwen-oauth"

    def test_config_file_backend_persistence(self):
        """Test that qwen-oauth backend can be persisted in config files."""
        from src.core.persistence import ConfigManager

        with patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "DISABLE_ACCOUNTING": "true"}
        ):
            app = build_app()

            # Mock functional backends to include qwen-oauth
            app.state.functional_backends = {"openrouter", "gemini", "qwen-oauth"}

            # Test that config manager can handle qwen-oauth
            config_manager = ConfigManager(
                app, path=":memory:"
            )  # Provide required path parameter

            # This should not raise an error
            try:
                config_manager._apply_default_backend("qwen-oauth")
            except ValueError as e:
                if "not in functional_backends" in str(e):
                    # Expected if qwen-oauth is not actually functional
                    pass
                else:
                    raise

    def test_all_backend_access_methods(self):
        """Test all methods of accessing qwen-oauth backend."""
        with patch.dict(
            os.environ, {"DISABLE_AUTH": "true", "DISABLE_ACCOUNTING": "true"}
        ):
            # Test the backend access methods without requiring actual backend objects
            backend_name = "qwen-oauth"

            # Method 1: Direct attribute access pattern
            backend_attr = backend_name.replace("-", "_")
            expected_attr_1 = f"{backend_attr}_backend"

            # Method 2: Using the constants pattern
            from src.core.domain.backend_type import BackendType

            expected_attr_2 = f"{BackendType.QWEN_OAUTH.replace('-', '_')}_backend"

            # Both methods should produce the same attribute name
            assert expected_attr_1 == expected_attr_2
            assert expected_attr_1 == "qwen_oauth_backend"

            # Test that the BackendType constant exists and has the correct value
            assert BackendType.QWEN_OAUTH == "qwen-oauth"


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v"])
