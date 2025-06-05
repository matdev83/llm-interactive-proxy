import pytest
from src.proxy_logic import (
    _process_text_for_commands,
    ProxyState,
    get_command_pattern,
    CommandParser,
)

class TestProcessTextForCommands:

    def test_no_commands(self):
        current_proxy_state = ProxyState()
        text = "This is a normal message without commands."
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == text
        assert not commands_found
        assert current_proxy_state.override_model is None

    def test_set_model_command(self):
        current_proxy_state = ProxyState()
        text = "Please use this model: !/set(model=gpt-4-turbo)"
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "Please use this model:" # Command is stripped
        assert commands_found
        assert current_proxy_state.override_model == "gpt-4-turbo"

    def test_set_model_command_with_slash(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=my/model-v1) This is a test."
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "This is a test."
        assert commands_found
        assert current_proxy_state.override_model == "my/model-v1"

    def test_unset_model_command(self):
        current_proxy_state = ProxyState()
        # First set a model
        pattern = get_command_pattern("!/")
        _process_text_for_commands("!/set(model=gpt-4)", current_proxy_state, pattern)
        assert current_proxy_state.override_model == "gpt-4"

        # Then unset it
        text = "Actually, !/unset(model) nevermind."
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "Actually, nevermind."
        assert commands_found
        assert current_proxy_state.override_model is None

    def test_multiple_commands_in_one_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=claude-2) Then, !/unset(model) and some text."
        # The behavior for multiple commands in one string might depend on implementation details.
        # Assuming commands are processed in order and proxy_state reflects the final command.
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "Then, and some text." # Both command texts are stripped and whitespace normalized
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
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == text # Unknown command is preserved
        assert commands_found # It was detected as a command pattern
        assert current_proxy_state.override_model is None # No known command to change state

    def test_command_at_start_of_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=test-model) The rest of the message."
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "The rest of the message."
        assert commands_found
        assert current_proxy_state.override_model == "test-model"

    def test_command_at_end_of_string(self):
        current_proxy_state = ProxyState()
        text = "Message before !/set(model=another-model)"
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "Message before"
        assert commands_found
        assert current_proxy_state.override_model == "another-model"

    def test_command_only_string(self):
        current_proxy_state = ProxyState()
        text = "!/set(model=command-only-model)"
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "" # Command is stripped, leaving empty string
        assert commands_found
        assert current_proxy_state.override_model == "command-only-model"

    def test_malformed_set_command(self):
        current_proxy_state = ProxyState()
        text = "!/set(mode=gpt-4)" # 'mode' instead of 'model'
        pattern = get_command_pattern("!/")
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "" # Command is stripped (or preserved based on unknown handling)
        assert commands_found
        assert current_proxy_state.override_model is None # State should not change

    def test_malformed_unset_command(self):
        current_proxy_state = ProxyState()
        # Example: !/unset(foo) - current logic might allow this if "foo" is treated as a key.
        # The existing logic for !/unset(model) checks "if 'model' in args".
        # So !/unset(foo) would not unset the model.
        pattern = get_command_pattern("!/")
        _process_text_for_commands("!/set(model=gpt-4)", current_proxy_state, pattern)
        assert current_proxy_state.override_model == "gpt-4"

        text = "!/unset(foo)"
        processed_text, commands_found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "" # Command is stripped
        assert commands_found
        assert current_proxy_state.override_model == "gpt-4" # Model remains set

    def test_set_and_unset_project(self):
        current_proxy_state = ProxyState()
        pattern = get_command_pattern("!/")
        processed_text, _ = _process_text_for_commands("!/set(project='abc def')", current_proxy_state, pattern)
        assert processed_text == ""
        assert current_proxy_state.project == "abc def"
        processed_text, _ = _process_text_for_commands("!/unset(project)", current_proxy_state, pattern)
        assert processed_text == ""
        assert current_proxy_state.project is None

    def test_unset_model_and_project_together(self):
        current_proxy_state = ProxyState()
        pattern = get_command_pattern("!/")
        _process_text_for_commands("!/set(model=foo)", current_proxy_state, pattern)
        _process_text_for_commands("!/set(project=bar)", current_proxy_state, pattern)
        assert current_proxy_state.override_model == "foo"
        assert current_proxy_state.project == "bar"
        processed_text, commands_found = _process_text_for_commands("!/unset(model, project)", current_proxy_state, pattern)
        assert processed_text == ""
        assert commands_found
        assert current_proxy_state.override_model is None
        assert current_proxy_state.project is None

    def test_set_interactive_mode(self):
        current_proxy_state = ProxyState()
        pattern = get_command_pattern("!/")
        text = "hello !/set(interactive-mode=ON)"
        processed_text, found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "hello"
        assert found
        assert current_proxy_state.interactive_mode is True

    def test_unset_interactive_mode(self):
        current_proxy_state = ProxyState(interactive_mode=True)
        pattern = get_command_pattern("!/")
        text = "!/unset(interactive)"
        processed_text, found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == ""
        assert found
        assert current_proxy_state.interactive_mode is False

    def test_hello_command(self):
        current_proxy_state = ProxyState()
        pattern = get_command_pattern("!/")
        text = "!/hello"
        processed_text, found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == ""
        assert found
        assert current_proxy_state.hello_requested is True

    def test_hello_command_with_text(self):
        current_proxy_state = ProxyState()
        pattern = get_command_pattern("!/")
        text = "Greetings !/hello friend"
        processed_text, found = _process_text_for_commands(text, current_proxy_state, pattern)
        assert processed_text == "Greetings friend"
        assert found
        assert current_proxy_state.hello_requested is True

    def test_unknown_command_removed_interactive(self):
        state = ProxyState(interactive_mode=True)
        parser = CommandParser(state, command_prefix="!/", preserve_unknown=False)
        text = "Hi !/foo(bar=1)"
        processed, found = parser.process_text(text)
        assert found
        assert processed == "Hi"
        assert parser.results[0].success is False
        assert "unknown command" in parser.results[0].message

