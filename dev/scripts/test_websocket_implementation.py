"""Quick validation script for WebSocket implementation.

This script tests that the WebSocket implementation loads correctly
and has the expected API surface.
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def test_websocket_client_api():
    """Test that OpenAIWebSocketClient has expected API."""
    from src.connectors.openai_websocket_client import OpenAIWebSocketClient

    # Check class exists and can be instantiated
    client = OpenAIWebSocketClient(api_key="test-key")

    # Check expected methods exist
    assert hasattr(client, "connect")
    assert hasattr(client, "disconnect")
    assert hasattr(client, "send_response_create")
    assert hasattr(client, "_ensure_connection")
    assert hasattr(client, "_event_to_processed_response")
    assert hasattr(client, "__aenter__")
    assert hasattr(client, "__aexit__")

    print("[OK] OpenAIWebSocketClient API validated")


def test_connector_integration():
    """Test that OpenAIConnector has WebSocket support."""
    from src.connectors.openai import OpenAIConnector

    # Check WebSocket-related methods/attributes exist
    assert hasattr(OpenAIConnector, "enable_websocket")
    assert hasattr(OpenAIConnector, "close")
    assert hasattr(OpenAIConnector, "_handle_websocket_response")

    print("[OK] OpenAIConnector WebSocket integration validated")


def test_controller_websocket_handler():
    """Test that ResponsesController has WebSocket handler."""
    from src.core.app.controllers.responses_controller import ResponsesController

    # Check WebSocket handler exists
    assert hasattr(ResponsesController, "handle_websocket_connection")
    assert hasattr(ResponsesController, "_handle_websocket_response_create")

    print("[OK] ResponsesController WebSocket handler validated")


def test_route_registration():
    """Test that WebSocket route can be found in controller registration."""
    # Check the source file directly since the route is defined inside the function
    with open("src/core/app/controllers/__init__.py") as f:
        source = f.read()

    # Check for WebSocket endpoint registration
    assert '@app.websocket("/v1/responses")' in source
    assert "responses_v1_ws" in source

    print("[OK] WebSocket route registration validated")


def test_configuration_schema():
    """Test that configuration schema includes WebSocket options."""
    import yaml

    schema_path = "config/schemas/app_config.schema.yaml"
    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    # Check for responses_api.websocket configuration
    assert "responses_api" in schema["properties"]
    responses_api = schema["properties"]["responses_api"]
    assert "websocket" in responses_api["properties"]

    websocket_config = responses_api["properties"]["websocket"]
    assert "frontend_enabled" in websocket_config["properties"]
    assert "backend_enabled" in websocket_config["properties"]

    print("[OK] Configuration schema validated")


def test_example_config():
    """Test that example config includes WebSocket settings."""
    with open("config/config.example.yaml") as f:
        content = f.read()

    # Check for WebSocket configuration section
    assert "responses_api:" in content
    assert "websocket:" in content
    assert "frontend_enabled:" in content
    assert "backend_enabled:" in content

    print("[OK] Example configuration validated")


def main():
    """Run all validation tests."""
    print("=" * 80)
    print("WebSocket Implementation Validation")
    print("=" * 80)
    print()

    try:
        test_websocket_client_api()
        test_connector_integration()
        test_controller_websocket_handler()
        test_route_registration()
        test_configuration_schema()
        test_example_config()

        print()
        print("=" * 80)
        print("[SUCCESS] All validation checks passed!")
        print("=" * 80)
        print()
        print("WebSocket implementation is ready. To test:")
        print("1. Run unit tests: pytest tests/unit/connectors/test_openai_websocket_client.py -v")
        print("2. Run controller tests: pytest tests/unit/core/app/controllers/test_responses_controller_websocket.py -v")
        print("3. Try demo script: python scripts/demo_responses_websocket.py --mode direct")
        print()

    except AssertionError as e:
        print(f"\nX Validation failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nX Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
