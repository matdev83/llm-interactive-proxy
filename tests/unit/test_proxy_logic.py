import pytest
from src.proxy_logic import (
    parse_arguments,
    _process_text_for_commands,
    process_commands_in_messages,
    ProxyState
)
from src.models import ChatMessage, MessageContentPart, MessageContentPartText

# Reset global proxy_state before each test function in this module if needed,
# or manage its state carefully within tests that modify it.
@pytest.fixture(autouse=True)
def reset_proxy_state():
    # Create a new instance or reset the existing global one
    # This assumes proxy_state in proxy_logic can be reassigned or has a reset method.
    # For simplicity, let's assume we can directly manipulate the global instance for tests
    # or that tests are independent enough. A better approach might be dependency injection for ProxyState.

    # If proxy_state is a global variable in proxy_logic.py:
    import src.proxy_logic
    src.proxy_logic.proxy_state = ProxyState() # Reset to a new instance

class TestParseArguments:
    def test_parse_valid_arguments(self):
        args_str = "model=gpt-4, temperature=0.7, max_tokens=100"
        expected = {"model": "gpt-4", "temperature": "0.7", "max_tokens": "100"}
        assert parse_arguments(args_str) == expected

    def test_parse_empty_arguments(self):
        assert parse_arguments("") == {}
        assert parse_arguments("   ") == {}

    def test_parse_arguments_with_slashes_in_model_name(self):
        args_str = "model=organization/model-name, temperature=0.5"
        expected = {"model": "organization/model-name", "temperature": "0.5"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_single_argument(self):
        args_str = "model=gpt-3.5-turbo"
        expected = {"model": "gpt-3.5-turbo"}
        assert parse_arguments(args_str) == expected

    def test_parse_arguments_with_spaces(self):
        args_str = " model = gpt-4 , temperature = 0.8 "
        expected = {"model": "gpt-4", "temperature": "0.8"}
        assert parse_arguments(args_str) == expected

    def test_parse_flag_argument(self):
        # E.g. !/unset(model) -> model is a key, not key=value
        args_str = "model"
        expected = {"model": True}
        assert parse_arguments(args_str) == expected

    def test_parse_mixed_arguments(self):
        args_str = "model=claude/opus, debug_mode"
        expected = {"model": "claude/opus", "debug_mode": True}
        assert parse_arguments(args_str) == expected


class TestProcessTextForCommands:

    @pytest.fixture(autouse=True)
    def ensure_clean_proxy_state(self):
        # This fixture ensures that proxy_state is reset for each test method
        # by depending on the higher-level reset_proxy_state fixture.
        # It's mainly for clarity if we had tests not needing reset_proxy_state.
        pass

    def test_no_commands(self):
        text = "This is a normal message without commands."
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == text
        assert not commands_found
        # assert src.proxy_logic.proxy_state.override_model is None # Check global state

    def test_set_model_command(self):
        text = "Please use this model: !/set(model=gpt-4-turbo)"
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "Please use this model:" # Command is stripped
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "gpt-4-turbo"

    def test_set_model_command_with_slash(self):
        text = "!/set(model=my/model-v1) This is a test."
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "This is a test."
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "my/model-v1"

    def test_unset_model_command(self):
        # First set a model
        _process_text_for_commands("!/set(model=gpt-4)")
        assert src.proxy_logic.proxy_state.override_model == "gpt-4"

        # Then unset it
        text = "Actually, !/unset(model) nevermind."
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "Actually, nevermind."
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model is None

    def test_multiple_commands_in_one_string(self):
        text = "!/set(model=claude-2) Then, !/unset(model) and some text."
        # The behavior for multiple commands in one string might depend on implementation details.
        # Assuming commands are processed in order and proxy_state reflects the final command.
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "Then, and some text." # Both command texts are stripped
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model is None # Unset was last

    def test_unknown_commands_are_preserved(self):
        text = "This is a !/unknown(command=value) that should be kept."
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == text # Unknown command is preserved
        assert commands_found # It was detected as a command pattern
        assert src.proxy_logic.proxy_state.override_model is None # No known command to change state

    def test_command_at_start_of_string(self):
        text = "!/set(model=test-model) The rest of the message."
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "The rest of the message."
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "test-model"

    def test_command_at_end_of_string(self):
        text = "Message before !/set(model=another-model)"
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "Message before"
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "another-model"

    def test_command_only_string(self):
        text = "!/set(model=command-only-model)"
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "" # Command is stripped, leaving empty string
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "command-only-model"

    def test_malformed_set_command(self):
        text = "!/set(mode=gpt-4)" # 'mode' instead of 'model'
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "" # Command is stripped (or preserved based on unknown handling)
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model is None # State should not change

    def test_malformed_unset_command(self):
        # Example: !/unset(foo) - current logic might allow this if "foo" is treated as a key.
        # The existing logic for !/unset(model) checks "if 'model' in args".
        # So !/unset(foo) would not unset the model.
        _process_text_for_commands("!/set(model=gpt-4)")
        assert src.proxy_logic.proxy_state.override_model == "gpt-4"

        text = "!/unset(foo)"
        processed_text, commands_found = _process_text_for_commands(text)
        assert processed_text == "" # Command is stripped
        assert commands_found
        assert src.proxy_logic.proxy_state.override_model == "gpt-4" # Model remains set


class TestProcessCommandsInMessages:

    @pytest.fixture(autouse=True)
    def ensure_clean_proxy_state(self):
        pass # Relies on the module-level reset_proxy_state

    def test_string_content_with_set_command(self):
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="user", content="Please use !/set(model=new-model) for this query.")
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "Hello"
        assert processed_messages[1].content == "Please use for this query."
        assert src.proxy_logic.proxy_state.override_model == "new-model"

    def test_multimodal_content_with_command(self):
        messages = [
            ChatMessage(role="user", content=[
                MessageContentPartText(type="text", text="What is this image? !/set(model=vision-model)"),
                MessageContentPart(type="image_url", image_url={"url": "fake.jpg"})
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        # Content list should have two parts if the text part wasn't entirely stripped
        # Current logic: text part is stripped of command, if text part becomes empty, it's removed.
        # Let's re-evaluate based on current _process_text_for_commands and process_commands_in_messages
        # _process_text_for_commands returns "" if only command was present.
        # process_commands_in_messages adds text part only if processed_text.strip() is true OR no command was found.
        # So, if "What is this image? " remains, it's kept.
        assert processed_messages[0].content[0].type == "text"
        assert processed_messages[0].content[0].text == "What is this image?"
        assert processed_messages[0].content[1].type == "image_url" # Image part preserved
        assert src.proxy_logic.proxy_state.override_model == "vision-model"

    def test_command_strips_text_part_empty_in_multimodal(self):
        messages = [
            ChatMessage(role="user", content=[
                MessageContentPartText(type="text", text="!/set(model=text-only)"), # This part becomes empty
                MessageContentPart(type="image_url", image_url={"url": "fake.jpg"})
            ])
        ]
        # The logic for handling empty text parts after command removal:
        # `if processed_text.strip(): new_content_parts.append(...)`
        # `elif not commands_found: new_content_parts.append(...)`
        # So if a command was found and processed_text is empty, the part is dropped.
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 1 # Text part should be removed
        assert processed_messages[0].content[0].type == "image_url"
        assert src.proxy_logic.proxy_state.override_model == "text-only"

    def test_command_strips_message_to_empty_multimodal(self):
        messages = [
            ChatMessage(role="user", content=[
                MessageContentPartText(type="text", text="!/set(model=empty-message-model)")
            ])
        ]
        # If all parts are removed (e.g., a single text part that's just a command),
        # the message itself might become empty.
        # `if isinstance(msg.content, list) and not msg.content: logger.info(...) continue`
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 0 # Message removed as content list became empty
        assert src.proxy_logic.proxy_state.override_model == "empty-message-model"

    def test_command_in_earlier_message_not_processed_if_later_has_command(self):
        # By default, current logic processes commands from the last message first and stops if commands are found.
        src.proxy_logic.proxy_state.override_model = "initial-model"
        messages = [
            ChatMessage(role="user", content="First message !/set(model=first-try)"),
            ChatMessage(role="user", content="Second message !/set(model=second-try)")
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message !/set(model=first-try)" # Unchanged
        assert processed_messages[1].content == "Second message" # Command stripped
        assert src.proxy_logic.proxy_state.override_model == "second-try" # Only second command processed

    def test_command_in_earlier_message_processed_if_later_has_no_command(self):
        src.proxy_logic.proxy_state.override_model = "initial-model"
        messages = [
            ChatMessage(role="user", content="First message with !/set(model=model-from-past)"),
            ChatMessage(role="user", content="Second message, plain text.")
        ]
        # The loop in process_commands_in_messages goes backward.
        # It processes msg index 1 (second message), finds no command.
        # Then processes msg index 0 (first message), finds command, processes it, and breaks.
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message with" # Command stripped
        assert processed_messages[1].content == "Second message, plain text." # Unchanged
        assert src.proxy_logic.proxy_state.override_model == "model-from-past"

    def test_no_commands_in_any_message(self):
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="user", content="How are you?")
        ]
        original_messages_copy = [m.model_copy(deep=True) for m in messages]
        processed_messages, processed = process_commands_in_messages(messages)
        assert not processed
        assert processed_messages == original_messages_copy # Messages should be unchanged
        assert src.proxy_logic.proxy_state.override_model is None

    def test_process_empty_messages_list(self):
        processed_messages, processed = process_commands_in_messages([])
        assert not processed
        assert processed_messages == []

    def test_message_with_only_command_string_content(self):
        messages = [
            ChatMessage(role="user", content="!/set(model=full-command-message)")
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed
        assert len(processed_messages) == 1
        # An empty string content is valid in OpenAI, so it should not be removed.
        assert processed_messages[0].content == ""
        assert src.proxy_logic.proxy_state.override_model == "full-command-message"

    def test_multimodal_text_part_preserved_if_empty_but_no_command_found(self):
        messages = [
            ChatMessage(role="user", content=[
                MessageContentPartText(type="text", text=""), # Empty text part
                MessageContentPart(type="image_url", image_url={"url": "fake.jpg"})
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert not processed # No commands found
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 2 # Both parts preserved
        assert processed_messages[0].content[0].type == "text"
        assert processed_messages[0].content[0].text == ""
        assert processed_messages[0].content[1].type == "image_url"

    def test_unknown_command_in_last_message(self):
        messages = [
            ChatMessage(role="user", content="Hello !/unknown(cmd) there")
        ]
        processed_messages, processed = process_commands_in_messages(messages)
        assert processed # Command pattern was found
        assert len(processed_messages) == 1
        assert processed_messages[0].content == "Hello !/unknown(cmd) there" # Preserved
        assert src.proxy_logic.proxy_state.override_model is None
