from unittest.mock import Mock

from src.core.services.failover_service import FailoverService


def test_get_failover_attempts() -> None:
    """Test that get_failover_attempts correctly parses route elements."""
    # Create a mock backend config with failover routes
    backend_config = Mock()
    backend_config.failover_routes = {
        "test-route": {
            "policy": "k",
            "elements": [
                "openai:gpt-4",
                "anthropic:claude-3-opus",
                "openrouter:mistralai/mistral-7b-instruct",
            ],
        }
    }

    # Create failover service
    service = FailoverService({})

    # Get failover attempts
    attempts = service.get_failover_attempts(backend_config, "test-route", "openai")

    # Verify we got the right number of attempts
    assert len(attempts) == 3

    # Verify the attempts have the correct backend and model values
    assert attempts[0].backend == "openai"
    assert attempts[0].model == "gpt-4"

    assert attempts[1].backend == "anthropic"
    assert attempts[1].model == "claude-3-opus"

    assert attempts[2].backend == "openrouter"
    assert attempts[2].model == "mistralai/mistral-7b-instruct"


def test_get_failover_attempts_empty_route() -> None:
    """Test that get_failover_attempts returns empty list for non-existent route."""
    # Create a mock backend config with no routes
    backend_config = Mock()
    backend_config.failover_routes = {}

    # Create failover service
    service = FailoverService({})

    # Get failover attempts for non-existent route
    attempts = service.get_failover_attempts(backend_config, "non-existent", "openai")

    # Verify we got an empty list
    assert attempts == []


def test_get_failover_attempts_invalid_element() -> None:
    """Test that get_failover_attempts handles invalid elements gracefully."""
    # Create a mock backend config with one valid and one invalid element
    backend_config = Mock()
    backend_config.failover_routes = {
        "test-route": {
            "policy": "k",
            "elements": [
                "openai:gpt-4",  # Valid
                "invalid-element",  # Invalid - no colon or slash
            ],
        }
    }

    # Create failover service
    service = FailoverService({})

    # Get failover attempts
    attempts = service.get_failover_attempts(backend_config, "test-route", "openai")

    # Verify we got both attempts
    assert len(attempts) == 2

    # Verify the valid attempt has the correct values
    assert attempts[0].backend == "openai"
    assert attempts[0].model == "gpt-4"

    # Invalid attempt falls back to provided backend type
    assert attempts[1].backend == "openai"
    assert attempts[1].model == "invalid-element"


def test_get_failover_attempts_infers_backend_from_context() -> None:
    """Elements without explicit backend should fall back to provided backend type."""

    backend_config = Mock()
    backend_config.failover_routes = {
        "test-route": {
            "policy": "k",
            "elements": [
                "gpt-4o",  # Implicit backend expected to be openai
            ],
        }
    }

    service = FailoverService({})

    attempts = service.get_failover_attempts(backend_config, "test-route", "openai")

    assert len(attempts) == 1
    assert attempts[0].backend == "openai"
    assert attempts[0].model == "gpt-4o"
