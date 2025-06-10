from unittest.mock import Mock

import pytest

import src.models as models
from src.command_parser import process_commands_in_messages
from src.proxy_logic import ProxyState


class TestProcessCommandsInMessages:

    @pytest.fixture(autouse=True)
    def setup_mock_app(self):
        # Create a mock app object with a state attribute and mock backends
        mock_openrouter_backend = Mock()
        mock_openrouter_backend.get_available_models.return_value = [
            "new-model",
            "text-only",
            "empty-message-model",
            "first-try",
            "second-try",
            "model-from-past",
            "full-command-message",
            "foo",
            "multi",
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
        mock_app_state.command_prefix = "!/"

        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    def test_string_content_with_set_command(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello"),
            models.ChatMessage(
                role="user",
                content="Please use !/set(model=openrouter:new-model) for this query.",
            ),
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "Hello"
        assert processed_messages[1].content == "Please use for this query."
        assert current_proxy_state.override_model == "new-model"

    def test_multimodal_content_with_command(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user",
                content=[
                    models.MessageContentPartText(
                        type="text", text="What is this image?"
                    ),
                    models.MessageContentPartImage(
                        type="image_url",
                        image_url=models.ImageURL(url="fake.jpg", detail=None),
                    ),
                ],
            )
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 2
        assert isinstance(
            processed_messages[0].content[0], models.MessageContentPartText
        )
        assert processed_messages[0].content[0].type == "text"
        assert processed_messages[0].content[0].text == "What is this image?"
        assert isinstance(
            processed_messages[0].content[1], models.MessageContentPartImage
        )
        assert processed_messages[0].content[1].type == "image_url"
        assert processed_messages[0].content[1].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model is None

    def test_command_strips_text_part_empty_in_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user",
                content=[
                    models.MessageContentPartText(
                        type="text", text="!/set(model=openrouter:text-only)"
                    ),
                    models.MessageContentPartImage(
                        type="image_url",
                        image_url=models.ImageURL(url="fake.jpg", detail=None),
                    ),
                ],
            )
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 1
        assert isinstance(
            processed_messages[0].content[0], models.MessageContentPartImage
        )
        assert processed_messages[0].content[0].type == "image_url"
        assert processed_messages[0].content[0].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model == "text-only"

    def test_command_strips_message_to_empty_multimodal(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user",
                content=[
                    models.MessageContentPartText(
                        type="text", text="!/set(model=openrouter:empty-message-model)"
                    )
                ],
            )
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 0
        assert current_proxy_state.override_model == "empty-message-model"

    def test_command_in_earlier_message_not_processed_if_later_has_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(
                role="user", content="First message !/set(model=openrouter:first-try)"
            ),
            models.ChatMessage(
                role="user", content="Second message !/set(model=openrouter:second-try)"
            ),
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 2
        assert (
            processed_messages[0].content
            == "First message !/set(model=openrouter:first-try)"
        )
        assert processed_messages[1].content == "Second message"
        assert current_proxy_state.override_model == "second-try"

    def test_command_in_earlier_message_processed_if_later_has_no_command(self):
        current_proxy_state = ProxyState()
        current_proxy_state.override_model = "initial-model"
        messages = [
            models.ChatMessage(
                role="user",
                content="First message with !/set(model=openrouter:model-from-past)",
            ),
            models.ChatMessage(role="user", content="Second message, plain text."),
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 2
        assert processed_messages[0].content == "First message with"
        assert processed_messages[1].content == "Second message, plain text."
        assert current_proxy_state.override_model == "model-from-past"

    def test_no_commands_in_any_message(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello"),
            models.ChatMessage(role="user", content="How are you?"),
        ]
        original_messages_copy = [m.model_copy(deep=True) for m in messages]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert not processed
        assert processed_messages == original_messages_copy
        assert current_proxy_state.override_model is None

    def test_process_empty_messages_list(self):
        current_proxy_state = ProxyState()
        processed_messages, processed = process_commands_in_messages(
            [], current_proxy_state, app=self.mock_app
        )
        assert not processed
        assert processed_messages == []
        assert (
            current_proxy_state.override_model is None
        )  # Ensure state is not affected

    def test_message_with_only_command_string_content(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user", content="!/set(model=openrouter:full-command-message)"
            )
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == ""
        assert current_proxy_state.override_model == "full-command-message"

    def test_multimodal_text_part_preserved_if_empty_but_no_command_found(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(
                role="user",
                content=[
                    models.MessageContentPartText(type="text", text=""),
                    models.MessageContentPartImage(
                        type="image_url",
                        image_url=models.ImageURL(url="fake.jpg", detail=None),
                    ),
                ],
            )
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert not processed
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 2
        assert processed_messages[0].content[0].type == "text"
        assert isinstance(
            processed_messages[0].content[0], models.MessageContentPartText
        )
        assert processed_messages[0].content[0].text == ""
        assert isinstance(
            processed_messages[0].content[1], models.MessageContentPartImage
        )
        assert processed_messages[0].content[1].type == "image_url"
        assert processed_messages[0].content[1].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model is None

    def test_unknown_command_in_last_message(self):
        current_proxy_state = ProxyState()
        messages = [
            models.ChatMessage(role="user", content="Hello !/unknown(cmd) there")
        ]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
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
            app=self.mock_app,  # Pass app here
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
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert processed_messages[0].content == "Line1 Line3"
        assert current_proxy_state.override_model == "multi"

    def test_set_project_in_messages(self):
        current_proxy_state = ProxyState()
        messages = [models.ChatMessage(role="user", content="!/set(project=proj1) hi")]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert processed_messages[0].content == "hi"
        assert current_proxy_state.project == "proj1"

    def test_unset_model_and_project_in_message(self):
        current_proxy_state = ProxyState()
        current_proxy_state.set_override_model("openrouter", "foo")
        current_proxy_state.set_project("bar")
        messages = [models.ChatMessage(role="user", content="!/unset(model, project)")]
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        assert len(processed_messages) == 1
        assert processed_messages[0].content == ""
        assert "!/unset(model, project)" not in processed_messages[0].content
        assert current_proxy_state.override_model is None
        assert current_proxy_state.project is None

    @pytest.mark.parametrize("variant", ["$/", "'$/'", '"$/"'])
    def test_set_command_prefix_variants(self, variant):
        current_proxy_state = ProxyState()
        msg = models.ChatMessage(
            role="user", content=f"!/set(command-prefix={variant})"
        )
        processed_messages, processed = process_commands_in_messages(
            [msg], current_proxy_state, app=self.mock_app
        )
        assert processed
        assert processed_messages[0].content == ""
        assert self.mock_app.state.command_prefix == "$/"

    def test_unset_command_prefix(self):
        current_proxy_state = ProxyState()
        msg_set = models.ChatMessage(role="user", content="!/set(command-prefix=~!)")
        process_commands_in_messages([msg_set], current_proxy_state, app=self.mock_app)
        assert self.mock_app.state.command_prefix == "~!"
        msg_unset = models.ChatMessage(role="user", content="~!unset(command-prefix)")
        processed_messages, processed = process_commands_in_messages(
            [msg_unset], current_proxy_state, app=self.mock_app, command_prefix="~!"
        )
        assert processed
        assert processed_messages[0].content == ""
        assert self.mock_app.state.command_prefix == "!/"
