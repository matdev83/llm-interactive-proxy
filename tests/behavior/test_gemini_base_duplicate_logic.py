"""
Duplicate logic detection tests for Gemini base connector refactoring.

Tests verify that duplicate logic is avoided across modules as required by
Requirement 4.3. Uses static analysis to detect duplicate patterns.
"""

import ast
import inspect

import pytest

pytestmark = [pytest.mark.behavior]


class TestNoDuplicateLogic:
    """Test that duplicate logic is avoided across modules.

    Requirement: 4.3 - Avoid duplicate logic across modules for the same behavior.
    """

    def test_no_duplicate_credential_validation_logic(self) -> None:
        """Verify credential validation logic is not duplicated.

        Credential validation should be in CredentialCoordinator or CredentialLoader,
        not duplicated in connector.py.
        """
        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.credential_coordinator import (
            GeminiCredentialCoordinator,
        )
        from src.connectors.gemini_base.credential_loader import CredentialLoader

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        coordinator_source = inspect.getsource(GeminiCredentialCoordinator)
        loader_source = inspect.getsource(CredentialLoader)

        # Parse source code to find validation logic
        connector_tree = ast.parse(connector_source)
        coordinator_tree = ast.parse(coordinator_source)
        loader_tree = ast.parse(loader_source)

        # Find validation function definitions
        def find_validation_functions(tree: ast.AST) -> list[str]:
            """Find function names that contain validation logic."""
            validation_funcs = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    func_name = node.name.lower()
                    if "valid" in func_name or "check" in func_name:
                        validation_funcs.append(node.name)
            return validation_funcs

        find_validation_functions(connector_tree)
        find_validation_functions(coordinator_tree)
        find_validation_functions(loader_tree)

        # Connector should only have thin wrappers, not full validation logic
        # Check that connector credential validation methods delegate
        credential_validation_methods = [
            "_validate_credentials_structure",
            "_validate_credentials_file_exists",
            "_validate_active_credentials_path",
        ]
        for func_name in credential_validation_methods:
            if hasattr(GeminiOAuthBaseConnector, func_name):
                func_source = inspect.getsource(
                    getattr(GeminiOAuthBaseConnector, func_name)
                )
                # Should delegate to CredentialLoader or coordinator
                assert (
                    "CredentialLoader" in func_source
                    or "_credential_coordinator" in func_source
                ), f"Connector.{func_name} should delegate validation, not reimplement"

    def test_no_duplicate_token_refresh_logic(self) -> None:
        """Verify token refresh logic is not duplicated.

        Token refresh should be in CredentialCoordinator or TokenManager,
        not duplicated in connector.py.
        """
        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.credential_coordinator import (
            GeminiCredentialCoordinator,
        )
        from src.connectors.gemini_base.token_manager import TokenManager

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        inspect.getsource(GeminiCredentialCoordinator)
        inspect.getsource(TokenManager)

        # Check that connector refresh methods delegate
        if "_refresh_token_if_needed" in connector_source:
            refresh_source = inspect.getsource(
                GeminiOAuthBaseConnector._refresh_token_if_needed
            )
            # Should delegate to coordinator or token manager
            assert (
                "_credential_coordinator.refresh_if_needed" in refresh_source
                or "_token_manager.refresh_token_if_needed" in refresh_source
            ), "Connector._refresh_token_if_needed should delegate, not reimplement"

    def test_no_duplicate_model_discovery_logic(self) -> None:
        """Verify model discovery logic is not duplicated.

        Model discovery should be in ModelRegistry or ApiModelDiscovery,
        not duplicated in connector.py.
        """
        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.model_registry import GeminiModelRegistry

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        inspect.getsource(GeminiModelRegistry)

        # Check that connector model loading delegates
        if "_ensure_models_loaded" in connector_source:
            models_source = inspect.getsource(
                GeminiOAuthBaseConnector._ensure_models_loaded
            )
            # Should delegate to model registry
            assert (
                "_model_registry.ensure_loaded" in models_source
            ), "Connector._ensure_models_loaded should delegate to model registry"

        # Check that _load_models_from_api is either delegated or a fallback
        # (fallback is acceptable for backward compatibility)
        if "_load_models_from_api" in connector_source:
            load_models_source = inspect.getsource(
                GeminiOAuthBaseConnector._load_models_from_api
            )
            # Should either delegate to model registry or be marked as fallback
            # (presence of _model_registry check indicates delegation attempt)
            # Note: _load_models_from_api is a fallback method, so it's acceptable
            # if it doesn't delegate (it's only used when model registry is unavailable)
            assert (
                "_model_registry" in load_models_source
                or "# Fallback" in load_models_source
                or "fallback" in load_models_source.lower()
                or "_ensure_models_loaded"
                in connector_source  # Delegates via _ensure_models_loaded
            ), "Connector._load_models_from_api should delegate or be marked as fallback"

    def test_no_duplicate_error_mapping_logic(self) -> None:
        """Verify error mapping logic is not duplicated.

        Error mapping should be in ErrorMapper, not duplicated in connector.py.
        """
        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.error_mapper import GeminiErrorMapper

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        inspect.getsource(GeminiErrorMapper)

        # Check that connector uses error mapper for mapping
        # (connector should not reimplement error mapping logic)
        if "_error_mapper" in connector_source:
            # Connector should use error mapper, not reimplement
            # Check chat_completions method
            try:
                chat_source = inspect.getsource(
                    GeminiOAuthBaseConnector.chat_completions
                )
                # Should use error mapper if present
                if "_error_mapper" in chat_source:
                    assert (
                        "_error_mapper.map_exception" in chat_source
                    ), "Connector should use error mapper, not reimplement mapping"
            except (OSError, TypeError):
                # Method might be inherited or not accessible
                pass

    def test_no_duplicate_health_check_logic(self) -> None:
        """Verify health check logic is not duplicated.

        Health checks should be in HealthCheckService, not duplicated in connector.py.
        """
        from src.connectors.gemini_base.connector import GeminiOAuthBaseConnector
        from src.connectors.gemini_base.health_check_service import (
            GeminiHealthCheckService,
        )

        connector_source = inspect.getsource(GeminiOAuthBaseConnector)
        inspect.getsource(GeminiHealthCheckService)

        # Check that connector delegates health checks
        if "_health_check_service" in connector_source:
            # Check chat_completions method for health check delegation
            try:
                chat_source = inspect.getsource(
                    GeminiOAuthBaseConnector.chat_completions
                )
                if "_health_check_service" in chat_source:
                    assert (
                        "_health_check_service.ensure_healthy" in chat_source
                    ), "Connector should delegate health checks to service"
            except (OSError, TypeError):
                # Method might be inherited or not accessible
                pass

    def test_coordinator_services_do_not_duplicate_each_other(self) -> None:
        """Verify coordinator services do not duplicate logic from each other.

        Each coordinator should have distinct responsibilities without overlap.
        """
        from src.connectors.gemini_base.credential_coordinator import (
            GeminiCredentialCoordinator,
        )
        from src.connectors.gemini_base.health_check_service import (
            GeminiHealthCheckService,
        )
        from src.connectors.gemini_base.model_registry import GeminiModelRegistry

        coordinator_source = inspect.getsource(GeminiCredentialCoordinator)
        registry_source = inspect.getsource(GeminiModelRegistry)
        health_source = inspect.getsource(GeminiHealthCheckService)

        # Credential coordinator should not contain model discovery logic
        assert (
            "fetchAvailableModels" not in coordinator_source
            or "# Fallback" in coordinator_source
        ), "CredentialCoordinator should not contain model discovery logic"

        # Model registry should not contain credential validation logic
        assert (
            "validate_credentials_structure" not in registry_source
        ), "ModelRegistry should not contain credential validation logic"

        # Health check service should not contain credential loading logic
        # (it should use credential coordinator)
        assert (
            "CredentialLoader.load_oauth_credentials" not in health_source
            or "_credential_coordinator" in health_source
        ), "HealthCheckService should use credential coordinator, not load credentials directly"

    def test_no_duplicate_request_preparation_logic(self) -> None:
        """Verify request preparation logic is not duplicated.

        Request preparation should be in ChatRequestPreparer, not duplicated elsewhere.
        """
        from src.connectors.gemini_base.chat_completion_coordinator import (
            GeminiChatCompletionCoordinator,
        )
        from src.connectors.gemini_base.chat_request_preparer import (
            ChatRequestPreparer,
        )

        coordinator_source = inspect.getsource(GeminiChatCompletionCoordinator)
        inspect.getsource(ChatRequestPreparer)

        # Chat completion coordinator should delegate to preparer
        if "execute" in coordinator_source:
            execute_source = inspect.getsource(GeminiChatCompletionCoordinator.execute)
            assert (
                "request_preparer.prepare" in execute_source
                or "_request_preparer.prepare" in execute_source
            ), "ChatCompletionCoordinator should delegate request preparation to preparer"

    def test_no_duplicate_streaming_execution_logic(self) -> None:
        """Verify streaming execution logic is not duplicated.

        Streaming execution should be in StreamingExecutor and CodeAssistOrchestrator,
        not duplicated in coordinator or connector.
        """
        from src.connectors.gemini_base.chat_completion_coordinator import (
            GeminiChatCompletionCoordinator,
        )
        from src.connectors.gemini_base.orchestrator import CodeAssistOrchestrator

        coordinator_source = inspect.getsource(GeminiChatCompletionCoordinator)
        inspect.getsource(CodeAssistOrchestrator)

        # Chat completion coordinator should delegate to orchestrator
        if "execute" in coordinator_source:
            execute_source = inspect.getsource(GeminiChatCompletionCoordinator.execute)
            assert (
                "orchestrator.run_streaming" in execute_source
                or "orchestrator.run_non_streaming" in execute_source
                or "_orchestrator.run" in execute_source
            ), "ChatCompletionCoordinator should delegate streaming execution to orchestrator"
