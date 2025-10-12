from src.core.app.stages.command import DefaultCommandStateService
from src.core.services.command_settings_service import CommandSettingsService


def _make_settings() -> CommandSettingsService:
    return CommandSettingsService(
        default_command_prefix="!/",
        default_api_key_redaction=True,
        default_disable_interactive_commands=False,
    )


def test_command_prefix_override_is_session_local() -> None:
    settings = _make_settings()
    state_service = DefaultCommandStateService(settings)

    state_service.update_command_prefix("$/")

    assert state_service.get_command_prefix() == "$/"
    assert settings.get_command_prefix() == "!/"


def test_api_key_redaction_override_is_session_local() -> None:
    settings = _make_settings()
    state_service = DefaultCommandStateService(settings)

    state_service.update_api_key_redaction(False)

    assert state_service.get_api_key_redaction_enabled() is False
    assert settings.get_api_key_redaction_enabled() is True


def test_disable_interactive_commands_override_is_session_local() -> None:
    settings = _make_settings()
    state_service = DefaultCommandStateService(settings)

    state_service.update_interactive_commands(True)

    assert state_service.get_disable_interactive_commands() is True
    assert settings.get_disable_interactive_commands() is False
