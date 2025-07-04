import pytest
from src.proxy_logic import (
    process_commands_in_messages,
    ProxyState
)
import src.models as models
from unittest.mock import Mock
from typing import List, Dict, Any, Union # Added for type hinting the helper


# Helper function for asserting multimodal message parts structure
def _assert_multimodal_message_parts(
    actual_content_parts: List[Union[models.MessageContentPartText, models.MessageContentPartImage]],
    expected_parts_data: List[Dict[str, Any]]
):
    assert len(actual_content_parts) == len(expected_parts_data), \
        f"Parts count mismatch: expected {len(expected_parts_data)}, got {len(actual_content_parts)}"
    for i, expected_part_data in enumerate(expected_parts_data):
        actual_part = actual_content_parts[i]
        expected_type_model = expected_part_data["model_type"]
        expected_type_str = expected_part_data["type_str"]

        assert isinstance(actual_part, expected_type_model), \
            f"Part {i} model type mismatch: expected {expected_type_model}, got {type(actual_part)}"
        assert actual_part.type == expected_type_str, \
            f"Part {i} type string mismatch: expected '{expected_type_str}', got '{actual_part.type}'"

        if expected_type_str == "text":
            assert actual_part.text == expected_part_data["text"], \
                f"Part {i} text content mismatch: expected '{expected_part_data['text']}', got '{actual_part.text}'"
        elif expected_type_str == "image_url":
            # Ensure actual_part has image_url attribute before accessing its 'url'
            assert hasattr(actual_part, 'image_url') and actual_part.image_url is not None, \
                f"Part {i} is of type image_url but has no image_url attribute or it is None."
            assert actual_part.image_url.url == expected_part_data["image_url"]["url"], \
                f"Part {i} image URL mismatch: expected '{expected_part_data['image_url']['url']}', got '{actual_part.image_url.url}'"

class TestProcessCommandsInMessages:

    @pytest.fixture(autouse=True)
    def setup_mock_app(self):
        # Create a mock app object with a state attribute and mock backends
        mock_openrouter_backend = Mock()
        mock_openrouter_backend.get_available_models.return_value = ["new-model", "text-only", "empty-message-model", "first-try", "second-try", "model-from-past", "full-command-message", "foo", "multi"]

        mock_gemini_backend = Mock()
        mock_gemini_backend.get_available_models.return_value = ["gemini-model"]

        mock_app_state = Mock()
        mock_app_state.openrouter_backend = mock_openrouter_backend
        mock_app_state.gemini_backend = mock_gemini_backend
        mock_app_state.functional_backends = {"openrouter", "gemini"}
        mock_app_state.command_prefix = "!/"
        
        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    def test_string_content_with_set_command(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello"),
            models.ChatMessage(role="user", content="Please use !/set(model=openrouter:new-model) for this query.")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
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
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)

        expected_parts_data = [
            {"model_type": models.MessageContentPartText, "type_str": "text", "text": "What is this image?"},
            {"model_type": models.MessageContentPartImage, "type_str": "image_url", "image_url": {"url": "fake.jpg"}}
        ]
        _assert_multimodal_message_parts(processed_messages[0].content, expected_parts_data)
        assert current_proxy_state.override_model is None

    def test_command_strips_text_part_empty_in_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text="!/set(model=openrouter:text-only)"),
                models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="fake.jpg", detail=None))
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)

        expected_parts_data = [
            {"model_type": models.MessageContentPartImage, "type_str": "image_url", "image_url": {"url": "fake.jpg"}}
        ]
        _assert_multimodal_message_parts(processed_messages[0].content, expected_parts_data)
        assert current_proxy_state.override_model == "text-only"

    def test_command_strips_message_to_empty_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text="!/set(model=openrouter:empty-message-model)")
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 0 # Message removed as it became empty
        assert current_proxy_state.override_model == "empty-message-model"

    def test_command_in_earlier_message_not_processed_if_later_has_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(role="user", content="First message !/set(model=openrouter:first-try)"),
            models.ChatMessage(role="user", content="Second message !/set(model=openrouter:second-try)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message !/set(model=openrouter:first-try)"
        assert processed_messages[1].content == "Second message"
        assert current_proxy_state.override_model == "second-try"

    def test_command_in_earlier_message_processed_if_later_has_no_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(role="user", content="First message with !/set(model=openrouter:model-from-past)"),
            models.ChatMessage(role="user", content="Second message, plain text.")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
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
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert not processed
        assert processed_messages == original_messages_copy
        assert current_proxy_state.override_model is None

    def test_process_empty_messages_list(self):
        current_proxy_state = ProxyState()
        processed_messages, processed = process_commands_in_messages([], current_proxy_state, app=self.mock_app)
        assert not processed
        assert processed_messages == []
        assert current_proxy_state.override_model is None

    def test_message_with_only_command_string_content(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="!/set(model=openrouter:full-command-message)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 0 # Message is removed as it becomes empty
        assert current_proxy_state.override_model == "full-command-message"

    def test_multimodal_text_part_preserved_if_empty_but_no_command_found(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content=[
                models.MessageContentPartText(type="text", text=""),
                models.MessageContentPartImage(type="image_url", image_url=models.ImageURL(url="fake.jpg", detail=None))
            ])
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)

        expected_parts_data = [
            {"model_type": models.MessageContentPartText, "type_str": "text", "text": ""},
            {"model_type": models.MessageContentPartImage, "type_str": "image_url", "image_url": {"url": "fake.jpg"}}
        ]
        _assert_multimodal_message_parts(processed_messages[0].content, expected_parts_data)
        assert current_proxy_state.override_model is None

    def test_unknown_command_in_last_message(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello !/unknown(cmd) there")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == "Hello !/unknown(cmd) there"
        assert current_proxy_state.override_model is None

    def test_custom_command_prefix(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello $$set(model=openrouter:foo)")
        ]
        processed_messages, processed = process_commands_in_messages(
            messages,
            current_proxy_state,
            app=self.mock_app,
            command_prefix="$$",
        )
        assert processed
        assert processed_messages[0].content == "Hello"
        assert current_proxy_state.override_model == "foo"

    def test_multiline_command_detection(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user",
                content="Line1\n!/set(model=openrouter:multi)\nLine3",
            )
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert processed_messages[0].content == "Line1 Line3"
        assert current_proxy_state.override_model == "multi"

    def test_set_project_in_messages(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="!/set(project=proj1) hi")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert processed_messages[0].content == "hi"
        assert current_proxy_state.project == "proj1"

    def test_unset_model_and_project_in_message(self):
        current_proxy_state = ProxyState()
        current_proxy_state.set_override_model("openrouter", "foo")
        current_proxy_state.set_project("bar")
        messages = [
            models.ChatMessage(role="user", content="!/unset(model, project)")
        ]
        processed_messages, processed = process_commands_in_messages(messages, current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 0 # Message removed as it becomes empty
        assert current_proxy_state.override_model is None
        assert current_proxy_state.project is None

    @pytest.mark.parametrize("variant", ["$/", "'$/'", '"$/"'])
    def test_set_command_prefix_variants(self, variant):
        current_proxy_state = ProxyState()
        msg = models.ChatMessage(role="user", content=f"!/set(command-prefix={variant})")
        processed_messages, processed = process_commands_in_messages([msg], current_proxy_state, app=self.mock_app)
        assert processed
        assert len(processed_messages) == 0 # Message removed as it becomes empty
        assert self.mock_app.state.command_prefix == "$/"

    def test_unset_command_prefix(self):
        current_proxy_state = ProxyState()
        # Set a custom prefix first
        msg_set = models.ChatMessage(role="user", content="!/set(command-prefix=~!)")
        _, processed_set = process_commands_in_messages([msg_set], current_proxy_state, app=self.mock_app)
        assert processed_set
        assert self.mock_app.state.command_prefix == "~!"

        # Now unset it using the new prefix
        msg_unset = models.ChatMessage(role="user", content="~!unset(command-prefix)")
        processed_messages, processed_unset = process_commands_in_messages(
            [msg_unset],
            current_proxy_state,
            app=self.mock_app,
            command_prefix="~!" # Important: parser needs to know current prefix
        )
        assert processed_unset
        assert len(processed_messages) == 0 # Message removed
        assert self.mock_app.state.command_prefix == "!/" # Check it reverted to default
