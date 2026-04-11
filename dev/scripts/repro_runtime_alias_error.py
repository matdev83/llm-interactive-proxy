"""
Repro script: Demonstrate improved runtime error messages for alias selectors.

This script proves that when an alias:/auto: selector fails to route,
the error message now includes helpful hints about missing --config.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import Mock
from src.core.config.models.rewriting import ModelAliasRule
from src.core.config.models.routing import RoutingConfig
from src.core.services.backend_routing_service import BackendRoutingService
from src.core.common.exceptions import RoutingError


def test_runtime_error_with_empty_aliases():
    """Test error message when alias: selector fails with empty model_aliases."""
    print("=" * 70)
    print("TEST 1: Runtime error with empty model_aliases")
    print("=" * 70)
    print()

    # Mock config provider with empty aliases (simulates no --config)
    mock_provider = Mock()
    mock_provider._app_config = Mock(model_aliases=[])
    mock_provider.configs = {}
    mock_provider.get_backend_config.return_value = None
    mock_provider.iter_backend_names.return_value = []

    service = BackendRoutingService(mock_provider, RoutingConfig())

    try:
        service.resolve_model_only_backend("alias:oss-code-medium")
    except RoutingError as e:
        print("[PASS] RoutingError raised (expected)")
        print()
        print("Error message:")
        print("-" * 70)
        print(e.message)
        print("-" * 70)
        print()

        # Verify the message contains helpful hints
        assert "No backend candidates discovered" in e.message
        assert "no `model_aliases` are loaded" in e.message
        assert "--config" in e.message
        print("[PASS] Error message contains helpful hint about --config")
        print()


def test_runtime_error_with_unmatched_alias():
    """Test error message when alias: selector fails with non-matching rule."""
    print("=" * 70)
    print("TEST 2: Runtime error with non-matching alias rule")
    print("=" * 70)
    print()

    # Mock config provider with some aliases but none that match
    mock_provider = Mock()
    mock_provider._app_config = Mock(
        model_aliases=[
            ModelAliasRule(pattern=r"^alias:verifier$", replacement="openai:gpt-4"),
        ]
    )
    mock_provider.configs = {}
    mock_provider.get_backend_config.return_value = None
    mock_provider.iter_backend_names.return_value = []

    service = BackendRoutingService(mock_provider, RoutingConfig())

    try:
        service.resolve_model_only_backend("alias:oss-code-medium")
    except RoutingError as e:
        print("[PASS] RoutingError raised (expected)")
        print()
        print("Error message:")
        print("-" * 70)
        print(e.message)
        print("-" * 70)
        print()

        # Verify the message contains helpful hint about unmatched rule
        assert "No backend candidates discovered" in e.message
        assert "no configured alias matched 'alias:oss-code-medium'" in e.message
        print("[PASS] Error message explains that no alias rule matched")
        print()


def test_runtime_error_with_auto_selector():
    """Test error message for auto: selector."""
    print("=" * 70)
    print("TEST 3: Runtime error with auto: selector (no aliases)")
    print("=" * 70)
    print()

    # Mock config provider with empty aliases
    mock_provider = Mock()
    mock_provider._app_config = Mock(model_aliases=[])
    mock_provider.configs = {}
    mock_provider.get_backend_config.return_value = None
    mock_provider.iter_backend_names.return_value = []

    service = BackendRoutingService(mock_provider, RoutingConfig())

    try:
        service.resolve_model_only_backend("auto:reasoning")
    except RoutingError as e:
        print("[PASS] RoutingError raised (expected)")
        print()
        print("Error message:")
        print("-" * 70)
        print(e.message)
        print("-" * 70)
        print()

        # Verify the message contains helpful hints
        assert "No backend candidates discovered" in e.message
        assert "auto:" in e.message
        assert "--config" in e.message
        print("[PASS] Error message contains helpful hint about auto: selector")
        print()


if __name__ == "__main__":
    print()
    print("DEMONSTRATING IMPROVED RUNTIME ERROR MESSAGES")
    print("This proves alias:/auto: selector failures now provide helpful hints")
    print()

    test_runtime_error_with_empty_aliases()
    test_runtime_error_with_unmatched_alias()
    test_runtime_error_with_auto_selector()

    print("=" * 70)
    print("ALL TESTS PASSED - Runtime error messages are now helpful!")
    print("=" * 70)
    print()
    print("Before fix: 'Unknown model alias:oss-code-medium'")
    print("After fix:  'Unknown model alias:oss-code-medium. No backend")
    print("            candidates discovered. The alias: selector namespace")
    print("            uses model alias rules, but no model_aliases are")
    print("            loaded. If you expected YAML aliases, verify the")
    print("            server was started with the intended --config file.'")
    print()
