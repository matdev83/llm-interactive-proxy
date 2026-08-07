"""
Integration tests for ToolAccessControlHandler registration in DI container.

These tests verify that the ToolAccessControlHandler is properly registered
with the ToolCallReactorService during application startup when access policies
are configured.
"""

import pytest
from src.core.config.app_config import AppConfig, ToolCallReactorConfig
from src.core.di.container import ServiceCollection


class TestToolAccessControlHandlerRegistration:
    """Test that ToolAccessControlHandler is properly registered in DI."""

    @pytest.fixture
    def service_collection(self):
        """Create a service collection."""
        return ServiceCollection()

    @pytest.fixture
    def config_with_policies(self):
        """Create an AppConfig with tool access policies configured."""
        # Create a new reactor config with policies
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": ["dangerous_.*"],
                    "block_message": "Tool blocked by test policy.",
                    "priority": 0,
                }
            ],
        )

        # Create config with updated session
        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        return config.model_copy(update={"session": session_config})

    @pytest.fixture
    def config_without_policies(self):
        """Create an AppConfig without tool access policies."""
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[],
        )

        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        return config.model_copy(update={"session": session_config})

    @pytest.fixture
    def config_reactor_disabled(self):
        """Create an AppConfig with tool call reactor disabled."""
        reactor_config = ToolCallReactorConfig(
            enabled=False,
            access_policies=[
                {
                    "name": "test_policy",
                    "model_pattern": ".*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": ["dangerous_.*"],
                    "block_message": "Tool blocked.",
                    "priority": 0,
                }
            ],
        )

        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        return config.model_copy(update={"session": session_config})

    @pytest.mark.asyncio
    async def test_tool_access_policy_service_is_registered(
        self, service_collection, config_with_policies
    ):
        """Verify ToolAccessPolicyService is registered in DI container."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_access_policy_service import (
            ToolAccessPolicyService,
        )

        # Register services
        register_core_services(service_collection, config_with_policies)
        provider = service_collection.build_service_provider()

        # Verify service can be resolved
        policy_service = provider.get_service(ToolAccessPolicyService)
        assert policy_service is not None, "ToolAccessPolicyService must be registered"

        # Verify it loaded the policies
        assert len(policy_service._policies) > 0, "Policies should be loaded"
        assert policy_service._policies[0].name == "test_policy"

    @pytest.mark.asyncio
    async def test_tool_access_control_handler_is_registered_with_policies(
        self, service_collection, config_with_policies
    ):
        """Verify ToolAccessControlHandler is registered when policies are configured."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_call_handlers.tool_access_control_handler import (
            ToolAccessControlHandler,
        )
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Register services
        register_core_services(service_collection, config_with_policies)
        provider = service_collection.build_service_provider()

        # Verify reactor service is registered
        reactor = provider.get_service(ToolCallReactorService)
        assert reactor is not None, "ToolCallReactorService must be registered"

        # Verify handler is registered in the reactor
        handler_names = list(reactor._handlers.keys())
        assert (
            "tool_access_control_handler" in handler_names
        ), "ToolAccessControlHandler must be registered in reactor"

        # Verify handler has correct priority
        tool_access_handler = reactor._handlers.get("tool_access_control_handler")
        assert tool_access_handler is not None
        assert isinstance(tool_access_handler, ToolAccessControlHandler)
        assert (
            tool_access_handler.priority == 90
        ), "Handler should have priority 90 (after dangerous-command handler at 100)"

    @pytest.mark.asyncio
    async def test_tool_access_control_handler_not_registered_without_policies(
        self, service_collection, config_without_policies
    ):
        """Verify ToolAccessControlHandler is NOT registered when no policies are configured."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Register services
        register_core_services(service_collection, config_without_policies)
        provider = service_collection.build_service_provider()

        # Verify reactor service is registered
        reactor = provider.get_service(ToolCallReactorService)
        assert reactor is not None, "ToolCallReactorService must be registered"

        # Verify handler is NOT registered when no policies exist
        handler_names = list(reactor._handlers.keys())
        assert (
            "tool_access_control_handler" not in handler_names
        ), "ToolAccessControlHandler should NOT be registered without policies"

    @pytest.mark.asyncio
    async def test_tool_access_control_handler_not_registered_when_reactor_disabled(
        self, service_collection, config_reactor_disabled
    ):
        """Verify ToolAccessControlHandler is NOT registered when reactor is disabled."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Register services
        register_core_services(service_collection, config_reactor_disabled)
        provider = service_collection.build_service_provider()

        # Verify reactor service is registered
        reactor = provider.get_service(ToolCallReactorService)
        assert reactor is not None, "ToolCallReactorService must be registered"

        # Verify no handlers are registered when reactor is disabled
        assert (
            len(reactor._handlers) == 0
        ), "No handlers should be registered when reactor is disabled"

    @pytest.mark.asyncio
    async def test_handler_priority_ordering(
        self, service_collection, config_with_policies
    ):
        """Verify ToolAccessControlHandler has correct priority relative to other handlers."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Register services
        register_core_services(service_collection, config_with_policies)
        provider = service_collection.build_service_provider()

        # Get reactor
        reactor = provider.get_service(ToolCallReactorService)
        assert reactor is not None

        # Find tool access control handler
        tool_access_handler = reactor._handlers.get("tool_access_control_handler")
        assert tool_access_handler is not None

        # Find unified security handler (if registered)
        dangerous_handler = reactor._handlers.get("unified_tool_security_handler")

        # If dangerous command handler exists, verify priority ordering
        if dangerous_handler:
            assert (
                tool_access_handler.priority < dangerous_handler.priority
            ), "ToolAccessControlHandler (90) should run after UnifiedToolSecurityHandler (100)"

    @pytest.mark.asyncio
    async def test_handler_receives_policy_service_dependency(
        self, service_collection, config_with_policies
    ):
        """Verify ToolAccessControlHandler receives ToolAccessPolicyService as dependency."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_call_handlers.tool_access_control_handler import (
            ToolAccessControlHandler,
        )
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Register services
        register_core_services(service_collection, config_with_policies)
        provider = service_collection.build_service_provider()

        # Get reactor
        reactor = provider.get_service(ToolCallReactorService)
        assert reactor is not None

        # Find tool access control handler
        tool_access_handler = reactor._handlers.get("tool_access_control_handler")
        assert tool_access_handler is not None
        assert isinstance(tool_access_handler, ToolAccessControlHandler)

        # Verify handler has policy service
        assert (
            tool_access_handler._policy_service is not None
        ), "Handler must have policy service injected"

    @pytest.mark.asyncio
    async def test_multiple_policies_are_loaded(self, service_collection):
        """Verify multiple access policies are loaded correctly."""
        from src.core.di.services import register_core_services
        from src.core.services.tool_access_policy_service import (
            ToolAccessPolicyService,
        )

        # Create config with multiple policies
        reactor_config = ToolCallReactorConfig(
            enabled=True,
            access_policies=[
                {
                    "name": "policy1",
                    "model_pattern": "gpt-.*",
                    "default_policy": "allow",
                    "allowed_patterns": [],
                    "blocked_patterns": ["dangerous_.*"],
                    "block_message": "Policy 1 block.",
                    "priority": 10,
                },
                {
                    "name": "policy2",
                    "model_pattern": "claude-.*",
                    "default_policy": "deny",
                    "allowed_patterns": ["read_.*"],
                    "blocked_patterns": [],
                    "block_message": "Policy 2 block.",
                    "priority": 5,
                },
            ],
        )

        config = AppConfig()
        session_config = config.session.model_copy(
            update={"tool_call_reactor": reactor_config}
        )
        config = config.model_copy(update={"session": session_config})

        # Register services
        register_core_services(service_collection, config)
        provider = service_collection.build_service_provider()

        # Verify policy service loaded both policies
        policy_service = provider.get_service(ToolAccessPolicyService)
        assert policy_service is not None
        assert len(policy_service._policies) == 2

        # Verify policies are sorted by priority (highest first)
        assert policy_service._policies[0].name == "policy1"
        assert policy_service._policies[0].priority == 10
        assert policy_service._policies[1].name == "policy2"
        assert policy_service._policies[1].priority == 5

    @pytest.mark.asyncio
    async def test_handler_registration_logs_policy_count(
        self, service_collection, config_with_policies, caplog
    ):
        """Verify handler registration logs the number of policies loaded."""
        import logging

        from src.core.di.services import register_core_services

        # Set log level to capture info messages
        caplog.set_level(logging.INFO)

        # Register services
        register_core_services(service_collection, config_with_policies)
        provider = service_collection.build_service_provider()

        # Build the provider to trigger handler registration
        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        _ = provider.get_service(ToolCallReactorService)

        # Verify log message about handler registration
        log_messages = [record.message for record in caplog.records]
        handler_log = next(
            (
                msg
                for msg in log_messages
                if "ToolAccessControlHandler" in msg and "policies loaded" in msg
            ),
            None,
        )
        assert (
            handler_log is not None
        ), "Should log handler registration with policy count"
        assert "1 policies loaded" in handler_log or "1 policy loaded" in handler_log
