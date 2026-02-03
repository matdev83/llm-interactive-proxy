"""Unit tests for AccessModeValidator DI registration."""

from src.core.config.app_config import load_config
from src.core.di.container import ServiceCollection
from src.core.di.registrations import security
from src.core.interfaces.access_mode_validator_interface import IAccessModeValidator
from src.core.services.access_mode_validator import AccessModeValidator


class TestAccessModeValidatorDIRegistration:
    """Test that AccessModeValidator is properly registered in DI container."""

    def test_access_mode_validator_registered_as_singleton(self):
        """Test that AccessModeValidator is registered as a singleton."""
        # Arrange
        services = ServiceCollection()
        config = load_config()
        security.register(services, config)
        provider = services.build_service_provider()

        # Act
        validator1 = provider.get_service(AccessModeValidator)
        validator2 = provider.get_service(AccessModeValidator)

        # Assert
        assert validator1 is not None
        assert validator2 is not None
        assert validator1 is validator2  # Same instance (singleton)

    def test_access_mode_validator_interface_resolvable(self):
        """Test that IAccessModeValidator interface can be resolved."""
        # Arrange
        services = ServiceCollection()
        config = load_config()
        security.register(services, config)
        provider = services.build_service_provider()

        # Act
        validator = provider.get_service(IAccessModeValidator)

        # Assert
        assert validator is not None
        assert isinstance(validator, AccessModeValidator)

    def test_interface_and_implementation_resolve_to_same_instance(self):
        """Test that interface and implementation resolve to the same singleton."""
        # Arrange
        services = ServiceCollection()
        config = load_config()
        security.register(services, config)
        provider = services.build_service_provider()

        # Act
        validator_via_interface = provider.get_service(IAccessModeValidator)
        validator_via_class = provider.get_service(AccessModeValidator)

        # Assert
        assert validator_via_interface is not None
        assert validator_via_class is not None
        assert validator_via_interface is validator_via_class  # Same instance

    def test_access_mode_validator_is_functional(self):
        """Test that the resolved validator is functional."""
        # Arrange
        services = ServiceCollection()
        config = load_config()
        security.register(services, config)
        provider = services.build_service_provider()
        validator = provider.get_service(IAccessModeValidator)

        import argparse

        args = argparse.Namespace(
            single_user_mode=False,
            multi_user_mode=False,
            allow_oauth_auto_replacement=False,
            enable_gemini_oauth_auto_backend_debugging_override=False,
            enable_gemini_oauth_free_backend_debugging_override=False,
            enable_gemini_oauth_plan_backend_debugging_override=False,
            enable_qwen_oauth_backend_debugging_override=False,
            enable_anthropic_oauth_backend_debugging_override=False,
            enable_openai_codex_backend_debugging_override=False,
            enable_opencode_zen_backend_debugging_override=False,
        )

        # Act & Assert - should not raise for default localhost config
        validator.validate(config, args)
