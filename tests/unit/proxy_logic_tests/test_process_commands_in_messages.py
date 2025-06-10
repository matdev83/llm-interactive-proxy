from unittest.mock import Mock
import logging # Added for caplog fixture

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
        # The text part had a command, so it's processed to empty and retained.
        assert len(processed_messages[0].content) == 2
        assert isinstance(
            processed_messages[0].content[0], models.MessageContentPartText
        )
        assert processed_messages[0].content[0].text == "" # Text part is now empty
        assert isinstance(
            processed_messages[0].content[1], models.MessageContentPartImage
        )
        assert processed_messages[0].content[1].type == "image_url"
        assert processed_messages[0].content[1].image_url.url == "fake.jpg"
        assert current_proxy_state.override_model == "text-only"

    def test_command_strips_message_to_empty_multimodal(self, caplog):
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
        caplog.set_level(logging.INFO)
        processed_messages, processed = process_commands_in_messages(
            messages, current_proxy_state, app=self.mock_app
        )
        assert processed
        # The message itself had a command, so it's retained even if its content list becomes effectively empty (contains an empty text part).
        assert len(processed_messages) == 1
        assert isinstance(processed_messages[0].content, list)
        assert len(processed_messages[0].content) == 1 # The list contains one part
        assert isinstance(processed_messages[0].content[0], models.MessageContentPartText)
        assert processed_messages[0].content[0].text == "" # The text part is empty
        assert current_proxy_state.override_model == "empty-message-model"

        assert any(
            "Retaining message" in record.message and "empty-message-model" not in record.message # ensure it's the message retention log
            for record in caplog.records if record.levelname == "INFO"
        ), "Should log retention of empty message due to executed command."

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

    def test_message_with_command_becomes_empty_and_is_retained(self, caplog):
        """
        Tests that a message containing a command, which becomes empty after processing,
        is retained in the final messages list. This verifies the fix in CommandParser.
        """
        from src.command_parser import CommandParser # Import locally for this test
        from src.models import ChatMessage # Import locally

        # Setup CommandParser instance directly
        # The mock_app setup in the fixture should provide necessary state for commands
        # like !/hello if they interact with app state.
        # For !/hello, it primarily affects proxy_state.hello_requested.
        current_proxy_state = ProxyState()
        parser = CommandParser(
            proxy_state=current_proxy_state,
            app=self.mock_app, # Use the mock_app from the fixture
            command_prefix="!/",
            functional_backends=self.mock_app.state.functional_backends
        )

        # Input message that will become empty after !/hello is processed
        # The <task> tags are removed by _strip_xml_tags called within process_text
        messages = [ChatMessage(role="user", content="<task>\n!/hello\n</task>")]

        caplog.set_level(logging.INFO) # To capture log messages

        final_messages, processed = parser.process_messages(messages)

        assert processed, "A command should have been processed."
        assert len(final_messages) == 1, "The message should be retained."

        # Check content based on how process_text and _strip_xml_tags work
        # !/hello results in empty string from process_text
        # <task></task> are stripped by _strip_xml_tags
        # So the final content should be an empty string or whitespace.
        assert final_messages[0].content.strip() == "", \
            f"Message content should be empty, but was: '{final_messages[0].content}'"

        assert any(
        result.name == "hello" and result.success for result in parser.results
        ), "The !/hello command should have been executed successfully."

        # Check for the specific log message
        assert any(
            "Retaining message" in record.message and
            "index 0" in record.message and
            "role user" in record.message and
            "executed command was processed in it" in record.message
            for record in caplog.records if record.levelname == "INFO"
        ), "Should log retention of empty message due to executed command."

        # Verify proxy_state was affected by !/hello as expected
        assert current_proxy_state.hello_requested, "ProxyState.hello_requested should be True after !/hello"
