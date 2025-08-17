"""
Integration tests for Qwen OAuth backend interactive command support.

These tests verify that the Qwen OAuth backend works correctly with interactive commands
in a real application environment.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_factory import build_app

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


# Check if OAuth credentials are available
def _has_qwen_oauth_credentials() -> bool:
    """Check if Qwen OAuth credentials are available."""
    home_dir = Path.home()
    creds_path = home_dir / ".qwen" / "oauth_creds.json"

    if not creds_path.exists():
        return False

    try:
        with open(creds_path, encoding="utf-8") as f:
            creds = json.load(f)
        return bool(creds.get("access_token") and creds.get("refresh_token"))
    except Exception:
        return False


QWEN_OAUTH_AVAILABLE = _has_qwen_oauth_credentials()


class TestQwenOAuthInteractiveCommandsIntegration:
    """Integration tests for Qwen OAuth interactive commands."""

    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for testing."""
        with patch("src.core.config.load_dotenv"):
            os.environ["LLM_BACKEND"] = "openrouter"  # Start with different backend
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

            app = build_app()
            yield app

    @pytest.fixture
    def client(self, qwen_oauth_app):
        """TestClient for the app."""
        with TestClient(qwen_oauth_app) as client:
            yield client

    def test_backend_attribute_exists(self, client):
        """Test that the qwen_oauth_backend attribute exists in app state."""
        # TestClient context manager triggers lifespan, so backends should be initialized
        app = client.app

        # Check that the backend attribute exists with underscores
        assert hasattr(app.state, "qwen_oauth_backend")

        # Get the backend object
        backend_obj = app.state.qwen_oauth_backend
        assert backend_obj is not None
        assert hasattr(backend_obj, "get_available_models")
        assert hasattr(backend_obj, "is_functional")

        print(f"Backend functional: {backend_obj.is_functional}")
        if backend_obj.is_functional:
            models = backend_obj.get_available_models()
            print(f"Available models: {len(models)} models")
            print(f"Models: {models[:5]}...")  # Show first 5 models

    def test_interactive_backend_setting_via_api(self, client):
        """Test setting qwen-oauth backend via API request."""
        payload = {
            "model": "openrouter:gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(backend=qwen-oauth) Backend set successfully",
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = client.post("/v1/chat/completions", json=payload)

        # Should not fail with routing error
        assert response.status_code == 200

        result = response.json()
        assert "choices" in result

        # Check if the command was processed
        content = result["choices"][0]["message"]["content"]
        assert isinstance(content, str)

        # The response should indicate backend was set
        if "backend set to qwen-oauth" in content.lower():
            print("✅ Backend setting command worked")
        else:
            print(f"Backend setting response: {content}")

    def test_interactive_model_setting_issue_reproduction(self, client):
        """Reproduce the issue with setting qwen-oauth models."""
        payload = {
            "model": "openrouter:gpt-3.5-turbo",
            "messages": [
                {
                    "role": "user",
                    "content": "!/set(model=qwen-oauth:qwen3-coder-plus) Model set successfully",
                }
            ],
            "max_tokens": 10,
            "temperature": 0.1,
            "stream": False,
        }

        response = client.post("/v1/chat/completions", json=payload)

        # Should not fail with routing error
        assert response.status_code == 200

        result = response.json()
        assert "choices" in result

        content = result["choices"][0]["message"]["content"]
        print(f"Model setting response: {content}")

        # Check if the issue is present
        if "not available/configured" in content:
            print("❌ Issue reproduced: Backend not found for model setting")
        elif "model set to qwen-oauth:qwen3-coder-plus" in content:
            print("✅ Model setting worked correctly")
        else:
            print(f"Unexpected response: {content}")

    def test_backend_object_accessibility_debug(self, client):
        """Debug test to check backend object accessibility."""
        print("\n=== Backend Object Accessibility Debug ===")

        app = client.app

        # Check app state attributes
        state_attrs = [attr for attr in dir(app.state) if not attr.startswith("_")]
        backend_attrs = [attr for attr in state_attrs if "backend" in attr]
        print(f"Backend-related attributes: {backend_attrs}")

        # Check specific backend access methods
        backend_name = "qwen-oauth"
        backend_attr = backend_name.replace("-", "_")
        full_attr_name = f"{backend_attr}_backend"

        print(f"Backend name: {backend_name}")
        print(f"Backend attr: {backend_attr}")
        print(f"Full attr name: {full_attr_name}")

        # Test attribute existence
        has_attr = hasattr(app.state, full_attr_name)
        print(f"hasattr(app.state, '{full_attr_name}'): {has_attr}")

        if has_attr:
            backend_obj = getattr(app.state, full_attr_name)
            print(f"Backend object: {backend_obj}")
            print(
                f"Backend functional: {backend_obj.is_functional if backend_obj else 'N/A'}"
            )

            if backend_obj and backend_obj.is_functional:
                models = backend_obj.get_available_models()
                print(f"Available models: {len(models)}")
                print(f"Has qwen3-coder-plus: {'qwen3-coder-plus' in models}")

        # Check functional backends
        functional_backends: set[str] = getattr(app.state, "functional_backends", set())
        print(f"Functional backends: {functional_backends}")
        print(f"qwen-oauth in functional: {'qwen-oauth' in functional_backends}")

    @pytest.mark.skipif(
        not QWEN_OAUTH_AVAILABLE, reason="Qwen OAuth credentials not available"
    )
    def test_model_setting_with_real_credentials(self, client):
        """Test model setting when OAuth credentials are actually available."""
        # First set the backend
        payload1 = {
            "model": "openrouter:gpt-3.5-turbo",
            "messages": [{"role": "user", "content": "!/set(backend=qwen-oauth)"}],
            "max_tokens": 5,
            "temperature": 0.1,
            "stream": False,
        }

        response1 = client.post("/v1/chat/completions", json=payload1)
        assert response1.status_code == 200

        # Then try to set the model
        payload2 = {
            "model": "openrouter:gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": "!/set(model=qwen-oauth:qwen3-coder-plus)"}
            ],
            "max_tokens": 5,
            "temperature": 0.1,
            "stream": False,
        }

        response2 = client.post("/v1/chat/completions", json=payload2)
        assert response2.status_code == 200

        result = response2.json()
        content = result["choices"][0]["message"]["content"]

        # With real credentials, this should work
        if "model set to qwen-oauth:qwen3-coder-plus" in content:
            print("✅ Model setting works with real credentials")
        else:
            print(f"Model setting with credentials: {content}")

    def test_direct_qwen_oauth_model_request(self, client):
        """Test making a direct request with qwen-oauth model."""
        payload = {
            "model": "qwen-oauth:qwen3-coder-plus",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 5,
            "temperature": 0.1,
            "stream": False,
        }

        response = client.post("/v1/chat/completions", json=payload)

        # Should not be a routing error (404, 422)
        assert response.status_code != 404
        assert response.status_code != 422

        # Might be 401 (auth error) or 200 (success) depending on credentials
        print(f"Direct qwen-oauth request status: {response.status_code}")

        if response.status_code == 200:
            response.json()
            print("✅ Direct qwen-oauth request succeeded")
        elif response.status_code == 401:
            print(
                "⚠️ Direct qwen-oauth request failed with auth error (expected without credentials)"
            )
        else:
            print(
                f"Direct qwen-oauth request failed with status {response.status_code}: {response.text}"
            )


class TestQwenOAuthCommandContext:
    """Test the command context system for qwen-oauth backend."""

    @pytest.fixture
    def qwen_oauth_app(self):
        """Create a FastAPI app configured for testing."""
        with patch("src.core.config.load_dotenv"):
            os.environ["LLM_BACKEND"] = "openrouter"
            os.environ["DISABLE_AUTH"] = "true"
            os.environ["DISABLE_ACCOUNTING"] = "true"
            os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"

            app = build_app()
            yield app

    def test_command_context_backend_access(self, client):
        """Test that command context can access qwen-oauth backend."""
        from src.core.domain.command_context import CommandContext

        app = client.app

        # Create a command context
        context = CommandContext(app)

        # Test getting the backend through context
        backend_obj = context.get_backend("qwen-oauth")

        print(f"Context backend access: {backend_obj is not None}")

        if backend_obj:
            print(f"Backend functional: {backend_obj.is_functional}")
            print(f"Backend type: {type(backend_obj).__name__}")
        else:
            print("❌ Command context could not access qwen-oauth backend")

            # Debug: check what backends are available
            available_backends = []
            for backend_name in ["openrouter", "gemini", "qwen-oauth", "anthropic"]:
                backend = context.get_backend(backend_name)
                if backend:
                    available_backends.append(backend_name)

            print(f"Available backends through context: {available_backends}")


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-s"])
