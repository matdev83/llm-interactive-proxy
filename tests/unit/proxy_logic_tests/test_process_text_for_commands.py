from unittest.mock import Mock

import pytest

from src.command_parser import (
    CommandParser,
    CommandParserConfig,
    process_commands_in_messages,
)
from src.models import ChatMessage
from src.proxy_logic import ProxyState


class TestProcessTextForCommands:

    @pytest.fixture(autouse=True)
    def setup_mock_app(self):
        # Create a mock app object with a state attribute and mock backends
        mock_openrouter_backend = Mock()
        mock_openrouter_backend.get_available_models.return_value = [
            "gpt-4-turbo",
            "my/model-v1",
            "gpt-4",
            "claude-2",
            "test-model",
            "another-model",
            "command-only-model",
            "multi",
            "foo",
        ]

        mock_gemini_backend = Mock()
        mock_gemini_backend.get_available_models.return_value = ["gemini-model"]

        mock_app_state = Mock()
        mock_app_state.openrouter_backend = mock_openrouter_backend
        mock_app_state.gemini_backend = mock_gemini_backend
        mock_app_state.functional_backends = {
            "openrouter",
            "gemini",
        }  # Add functional backends
        mock_app_state.default_api_key_redaction_enabled = True
        mock_app_state.api_key_redaction_enabled = True

        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    def test_no_commands(self):
        current_proxy_state = ProxyState()
        text = "This is a normal message without commands."
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == text
        assert not commands_found
        assert current_proxy_state.override_model is None

    def test_set_model_command(self):
        current_proxy_state = ProxyState()
        text = "Please use this model: !/set(model=openrouter:gpt-4-turbo)"
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Please use this model:"  # Command is stripped
        assert commands_found
        assert current_proxy_state.override_model == "gpt-4-turbo"

    def test_set_model_command_with_slash(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=openrouter:my/model-v1) This is a test."
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "This is a test."
        assert commands_found
        assert current_proxy_state.override_model == "my/model-v1"

    def test_unset_model_command(self):
        current_proxy_state = ProxyState()
        # First set a model
        process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:gpt-4)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        assert current_proxy_state.override_model == "gpt-4"

        # Then unset it
        text = "Actually, !/unset(model) nevermind."
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Actually, nevermind."
        assert commands_found
        assert current_proxy_state.override_model is None

    def test_multiple_commands_in_one_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=openrouter:claude-2) Then, !/unset(model) and some text."
        # The behavior for multiple commands in one string might depend on implementation details.
        # Assuming commands are processed in order and proxy_state reflects the final command.
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert (
            processed_text == "Then, !/unset(model) and some text."
        )  # Only the first command is processed and stripped.
        assert commands_found
        # This assertion needs to be re-evaluated based on the actual logic of _process_text_for_commands
        # If commands are processed from right to left (due to regex finditer and string slicing):
        # 1. !/unset(model) is processed -> model becomes None
        # 2. !/set(model=claude-2) is processed -> model becomes "claude-2"
        # However, the original test asserted "claude-2", implying the set was "last".
        # Let's assume the logic processes commands such that the *first* encountered set sticks if not later unset.
        # Or, if it processes left-to-right, the last command affecting a property wins.
        # The current _process_text_for_commands processes from right to left.
        # So, !/unset(model) is found first, then !/set(model=claude-2).
        # When !/unset(model) is processed, it unsets.
        # When !/set(model=claude-2) is processed, it sets.
        # So the final state should be "claude-2".
        assert current_proxy_state.override_model == "claude-2"

    def test_unknown_commands_are_preserved(self):
        current_proxy_state = ProxyState()
        text = "This is a !/unknown(command=value) that should be kept."
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == text  # Unknown command is preserved
        assert commands_found  # It was detected as a command pattern
        assert (
            current_proxy_state.override_model is None
        )  # No known command to change state

    def test_command_at_start_of_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=openrouter:test-model) The rest of the message."
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "The rest of the message."
        assert commands_found
        assert current_proxy_state.override_model == "test-model"

    def test_command_at_end_of_string(self):
        current_proxy_state = ProxyState()
        text = "Message before !/set(model=openrouter:another-model)"
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Message before"
        assert commands_found
        assert current_proxy_state.override_model == "another-model"

    def test_command_only_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=openrouter:command-only-model)"
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""  # Command is stripped, leaving empty string
        assert commands_found
        assert current_proxy_state.override_model == "command-only-model"

    def test_malformed_set_command(self):
        current_proxy_state = ProxyState()
        text = "!/set(mode=gpt-4)"  # 'mode' instead of 'model'
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert (
            processed_text == "set: no valid parameters provided or action taken"
        ) # Match the actual message from SetCommand
        assert commands_found
        assert current_proxy_state.override_model is None  # State should not change

    def test_malformed_unset_command(self):
        current_proxy_state = ProxyState()
        # Example: !/unset(foo) - current logic might allow this if "foo" is treated as a key.
        # The existing logic for !/unset(model) checks "if 'model' in args".
        # So !/unset(foo) would not unset the model.
        process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:gpt-4)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        assert current_proxy_state.override_model == "gpt-4"

        text = "!/unset(foo)"
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "unset: nothing to do"
        assert commands_found
        assert current_proxy_state.override_model == "gpt-4"  # Model remains set

    def test_set_and_unset_project(self):
        current_proxy_state = ProxyState()
        processed_messages, _ = process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(project='abc def')")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert current_proxy_state.project == "abc def"
        processed_messages, _ = process_commands_in_messages(
            [ChatMessage(role="user", content="!/unset(project)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert current_proxy_state.project is None

    def test_unset_model_and_project_together(self):
        current_proxy_state = ProxyState()
        process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:foo)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(project=bar)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        assert current_proxy_state.override_model == "foo"
        assert current_proxy_state.project == "bar"
        processed_messages, commands_found = process_commands_in_messages(
            [ChatMessage(role="user", content="!/unset(model, project)")],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert commands_found
        assert current_proxy_state.override_model is None
        assert current_proxy_state.project is None

    def test_set_interactive_mode(self):
        current_proxy_state = ProxyState()
        text = "hello !/set(interactive-mode=ON)"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "hello"
        assert found
        assert current_proxy_state.interactive_mode

    def test_unset_interactive_mode(self):
        current_proxy_state = ProxyState(interactive_mode=True)
        text = "!/unset(interactive)"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert found
        assert not current_proxy_state.interactive_mode

    def test_hello_command(self):
        current_proxy_state = ProxyState()
        text = "!/hello"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert found
        assert current_proxy_state.hello_requested

    def test_hello_command_with_text(self):
        current_proxy_state = ProxyState()
        text = "Greetings !/hello friend"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Greetings friend"
        assert found
        assert current_proxy_state.hello_requested

    def test_unknown_command_removed_interactive(self):
        state = ProxyState(interactive_mode=True)
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            preserve_unknown=False,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        text = "Hi !/foo(bar=1)"
        processed_messages, found = parser.process_messages(
            [ChatMessage(role="user", content=text)]
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == "Hi"
        assert not parser.command_results[0].success
        assert "cmd not found" in parser.command_results[0].message # Match actual error message

    def test_set_invalid_model_interactive(self):
        state = ProxyState(interactive_mode=True)
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            preserve_unknown=False,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")]
        )
        assert state.override_model is None
        assert not state.invalid_override
        assert not parser.command_results[0].success
        assert "not available" in parser.command_results[0].message

    def test_set_invalid_model_noninteractive(self):
        state = ProxyState()
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            preserve_unknown=True,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")]
        )
        assert state.override_backend is None
        assert state.override_model is None

    def test_set_backend(self):
        state = ProxyState()
        # from src import main as app_main # No longer needed
        # app_main.app.state.functional_backends = {"openrouter", "gemini"} # No longer needed
        text = "!/set(backend=gemini) hi"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == "hi"
        assert state.override_backend == "gemini"
        assert state.override_model is None

    def test_unset_backend(self):
        state = ProxyState()
        state.set_override_backend("gemini")
        text = "!/unset(backend)"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == ""
        assert state.override_backend is None

    def test_set_redact_api_keys_flag(self):
        state = ProxyState()
        text = "!/set(redact-api-keys-in-prompts=false)"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert processed == ""
        assert found
        assert not self.mock_app.state.api_key_redaction_enabled

    def test_unset_redact_api_keys_flag(self):
        state = ProxyState()
        self.mock_app.state.api_key_redaction_enabled = False
        text = "!/unset(redact-api-keys-in-prompts)"
        processed_messages, found = process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert processed == ""
        assert found
        assert (
            self.mock_app.state.api_key_redaction_enabled
            == self.mock_app.state.default_api_key_redaction_enabled
        )