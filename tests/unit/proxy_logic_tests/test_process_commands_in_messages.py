import pytest
from src.proxy_logic import (
    process_commands_in_messages,
    ProxyState
)
import src.models as models

class TestProcessCommandsInMessages:

    def test_string_content_with_set_command(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello"),
            models.ChatMessage(role="user", content="Please use !/set(model=new-model) for this query.")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "Hello"
        assert processed_messages[1].content == "Please use for this query."
        assert current_proxy_state.override_model == "new-model"

    def test_multimodal_content_with_command(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text="What is this image?"),
                models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="fake.jpg", detail=None))
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 2
        assert isinstance(processed_messages[0].content[0], models.MessageContentPartText)
        assert processed_messages[0].content[0].type == "text"
        assert processed_messages[0].content[0].text == "What is this image?"
        assert isinstance(processed_messages[0].content[1], models.MessageContentPartImage)
        assert processed_messages[0].content[1].type == "image_url"
        assert processed_messages[0].content[1].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model is None

    def test_command_strips_text_part_empty_in_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text="!/set(model=text-only)"),
                models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="fake.jpg", detail=None))
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 1
        assert isinstance(processed_messages[0].content[0], models.MessageContentPartImage)
        assert processed_messages[0].content[0].type == "image_url"
        assert processed_messages[0].content[0].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model == "text-only"

    def test_command_strips_message_to_empty_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text="!/set(model=empty-message-model)")
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 0
        assert current_proxy_state.override_model == "empty-message-model"

    def test_command_in_earlier_message_not_processed_if_later_has_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(role="user", content="First message !/set(model=first-try)"),
            models.ChatMessage(role="user", content="Second message !/set(model=second-try)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message !/set(model=first-try)"
        assert processed_messages[1].content == "Second message"
        assert current_proxy_state.override_model == "second-try"

    def test_command_in_earlier_message_processed_if_later_has_no_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(role="user", content="First message with !/set(model=model-from-past)"),
            models.ChatMessage(role="user", content="Second message, plain text.")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message with"
        assert processed_messages[1].content == "Second message, plain text."
        assert current_proxy_state.override_model == "model-from-past"

    def test_no_commands_in_any_message(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello"),
            models.ChatMessage(role="user", content="How are you?")
        ]
        original_messages_copy = [m.model_copy(deep=True) for m in messages]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert not processed
        assert processed_messages == original_messages_copy
        assert current_proxy_state.override_model is None

    def test_process_empty_messages_list(self):
        current_proxy_state = ProxyState()
        processed_messages, processed = process_commands_in_messages([], current_proxy_state)
        assert not processed
        assert processed_messages == []
        assert current_proxy_state.override_model is None # Ensure state is not affected

    def test_message_with_only_command_string_content(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="!/set(model=full-command-message)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == ""
        assert current_proxy_state.override_model == "full-command-message"

    def test_multimodal_text_part_preserved_if_empty_but_no_command_found(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text=""),
                models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="fake.jpg", detail=None))
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 2
        assert processed_messages[0].content[0].type == "text"
        assert isinstance(processed_messages[0].content[0], models.MessageContentPartText)
        assert processed_messages[0].content[0].text == ""
        assert isinstance(processed_messages[0].content[1], models.MessageContentPartImage)
        assert processed_messages[0].content[1].type == "image_url"
        assert processed_messages[0].content[1].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model is None

    def test_unknown_command_in_last_message(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello !/unknown(cmd) there")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == "Hello !/unknown(cmd) there"
        assert current_proxy_state.override_model is None

    def test_custom_command_prefix(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello $$set(model=foo)")
        ]
        processed_messages, processed = process_commands_in_messages(
            messages,
            current_proxy_state,
            command_prefix="$$",
        )
        assert processed
        assert processed_messages[0].content == "Hello"
        assert current_proxy_state.override_model == "foo"

    def test_set_project_in_messages(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="!/set(project=proj1) hi")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert processed_messages[0].content == "hi"
        assert current_proxy_state.project == "proj1"

    def test_unset_model_and_project_in_message(self):
        current_proxy_state = ProxyState()
        current_proxy_state.set_override_model("foo")
        current_proxy_state.set_project("bar")
        messages = [
            models.ChatMessage(role="user", content="!/unset(model, project)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state)
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == ""
        assert current_proxy_state.override_model is None
        assert current_proxy_state.project is None
