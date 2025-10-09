from __future__ import annotations

from src.core.services.command_settings_service import CommandSettingsService


class TestCommandSettingsService:
    def test_compatibility_getters_reflect_current_values(self) -> None:
        service = CommandSettingsService(
            default_command_prefix="$/",
            default_api_key_redaction=False,
            default_disable_interactive_commands=True,
        )

        assert service.get_command_prefix() == "$/"
        assert service.get_api_key_redaction_enabled() is False
        assert service.get_disable_interactive_commands() is True

        service.command_prefix = "#/"
        service.api_key_redaction_enabled = True
        service.disable_interactive_commands = False

        assert service.get_command_prefix() == "#/"
        assert service.get_api_key_redaction_enabled() is True
        assert service.get_disable_interactive_commands() is False

    def test_reset_to_defaults_restores_original_values(self) -> None:
        service = CommandSettingsService(
            default_command_prefix="!/",
            default_api_key_redaction=True,
            default_disable_interactive_commands=False,
        )

        service.command_prefix = "#/"
        service.api_key_redaction_enabled = False
        service.disable_interactive_commands = True

        service.reset_to_defaults()

        assert service.command_prefix == "!/"
        assert service.api_key_redaction_enabled is True
        assert service.disable_interactive_commands is False
        assert service.get_command_prefix() == "!/"
        assert service.get_api_key_redaction_enabled() is True
        assert service.get_disable_interactive_commands() is False

