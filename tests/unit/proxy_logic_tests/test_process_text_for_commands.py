from typing import cast
from unittest.mock import Mock

import pytest
from src.command_parser import (
    CommandParser,
    CommandParserConfig,
    process_commands_in_messages,
)
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration.backend_config import BackendConfiguration
from src.core.domain.session import Session, SessionStateAdapter


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
        # Register backends via a fake BackendService on the service_provider to avoid legacy fallbacks

        class _FakeBackendService:
            def __init__(self, or_backend, gem_backend):
                self._backends = {"openrouter": or_backend, "gemini": gem_backend}

        service_provider = Mock()
        service_provider.get_required_service.return_value = _FakeBackendService(
            mock_openrouter_backend, mock_gemini_backend
        )

        mock_app_state.service_provider = service_provider
        mock_app_state.functional_backends = {"openrouter", "gemini"}
        mock_app_state.default_api_key_redaction_enabled = True
        mock_app_state.api_key_redaction_enabled = True

        self.mock_app = Mock()
        self.mock_app.state = mock_app_state

    @pytest.mark.asyncio
    async def test_no_commands(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "This is a normal message without commands."
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == text
        assert not commands_found
        assert session.state.backend_config.model is None

    @pytest.mark.asyncio
    async def test_set_model_command(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "Please use this model: !/set(model=openrouter:gpt-4-turbo)"
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Please use this model:"  # Command is stripped
        assert commands_found
        assert session.state.backend_config.model == "gpt-4-turbo"

    @pytest.mark.asyncio
    async def test_set_model_command_with_slash(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/set(model=openrouter:my/model-v1) This is a test."
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "This is a test."
        assert commands_found
        assert session.state.backend_config.model == "my/model-v1"

    @pytest.mark.asyncio
    async def test_unset_model_command(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        # First set a model
        new_backend_config = current_session_state.backend_config.with_model("gpt-4")
        session.state = current_session_state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )
        assert session.state.backend_config.model == "gpt-4"

        # Then unset it
        text = "Actually, !/unset(model) nevermind."
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, session.state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Actually, nevermind."
        assert commands_found
        assert session.state.backend_config.model is None

    @pytest.mark.asyncio
    async def test_multiple_commands_in_one_string(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/set(model=openrouter:claude-2) Then, !/unset(model) and some text."
        # The behavior for multiple commands in one string might depend on implementation details.
        # Assuming commands are processed in order and session.state reflects the final command.
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
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
        # 2. !/set(model=claude-2) is processed -> model becomes "claude-2".
        # So the final state should be "claude-2".
        assert session.state.backend_config.model == "claude-2"

    @pytest.mark.asyncio
    async def test_unknown_commands_are_preserved(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "This is a !/unknown(command=value) that should be kept."
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == text  # Unknown command is preserved
        assert commands_found  # It was detected as a command pattern
        assert (
            session.state.backend_config.model is None
        )  # No known command to change state

    @pytest.mark.asyncio
    async def test_command_at_start_of_string(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/set(model=openrouter:test-model) The rest of the message."
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "The rest of the message."
        assert commands_found
        assert session.state.backend_config.model == "test-model"

    @pytest.mark.asyncio
    async def test_command_at_end_of_string(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "Message before !/set(model=openrouter:another-model)"
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Message before"
        assert commands_found
        assert session.state.backend_config.model == "another-model"

    @pytest.mark.asyncio
    async def test_command_only_string(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/set(model=openrouter:command-only-model)"
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""  # Command is stripped, leaving empty string
        assert commands_found
        assert session.state.backend_config.model == "command-only-model"

    @pytest.mark.asyncio
    async def test_malformed_set_command(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/set(mode=gpt-4)"  # 'mode' instead of 'model'
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert (
            processed_text == "set: no valid parameters provided or action taken"
        )  # Match the actual message from SetCommand
        assert commands_found
        assert session.state.backend_config.model is None  # State should not change

    @pytest.mark.asyncio
    async def test_malformed_unset_command(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        # First set a model
        new_backend_config = current_session_state.backend_config.with_model("gpt-4")
        session.state = current_session_state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )
        assert session.state.backend_config.model == "gpt-4"

        text = "!/unset(foo)"
        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, session.state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "unset: nothing to do"
        assert commands_found
        assert session.state.backend_config.model == "gpt-4"  # Model remains set

    @pytest.mark.asyncio
    async def test_set_and_unset_project(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        processed_messages, _ = await process_commands_in_messages(
            [ChatMessage(role="user", content="!/set(project='abc def')")],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert session.state.project == "abc def"
        processed_messages, _ = await process_commands_in_messages(
            [ChatMessage(role="user", content="!/unset(project)")],
            cast(SessionStateAdapter, session.state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert session.state.project is None

    @pytest.mark.asyncio
    async def test_unset_model_and_project_together(self):
        session = Session(session_id="test_session")
        current_session_state = session.state

        # Set initial model and project
        new_backend_config = current_session_state.backend_config.with_model("foo")
        new_session_state = current_session_state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )
        new_session_state = new_session_state.with_project("bar")
        session.state = new_session_state

        processed_messages, commands_found = await process_commands_in_messages(
            [ChatMessage(role="user", content="!/unset(model, project)")],
            cast(SessionStateAdapter, session.state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert commands_found
        assert session.state.backend_config.model is None
        assert session.state.project is None

    @pytest.mark.asyncio
    async def test_set_interactive_mode(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "hello !/set(interactive-mode=ON)"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "hello"
        assert found
        assert session.state.interactive_just_enabled

    @pytest.mark.asyncio
    async def test_unset_interactive_mode(self):
        session = Session(session_id="test_session")
        current_session_state = session.state

        # Set initial interactive mode
        session.state = current_session_state.with_interactive_just_enabled(True)
        assert session.state.interactive_just_enabled

        text = "!/unset(interactive)"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, session.state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert found
        assert not session.state.interactive_just_enabled

    @pytest.mark.asyncio
    async def test_hello_command(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "!/hello"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert found
        assert session.state.hello_requested

    @pytest.mark.asyncio
    async def test_hello_command_with_text(self):
        session = Session(session_id="test_session")
        current_session_state = session.state
        text = "Greetings !/hello friend"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            cast(SessionStateAdapter, current_session_state),
            app=self.mock_app,
            command_prefix="!/",
        )
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "Greetings friend"
        assert found
        assert session.state.hello_requested

    @pytest.mark.asyncio
    async def test_unknown_command_removed_interactive(self):
        session = Session(session_id="test_session")
        state = session.state
        config = CommandParserConfig(
            proxy_state=cast(SessionStateAdapter, state),
            app=self.mock_app,
            preserve_unknown=False,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        text = "Hi !/foo(bar=1)"
        processed_messages, found = await parser.process_messages(
            [ChatMessage(role="user", content=text)]
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == "Hi"
        assert not parser.command_results[0].success
        assert (
            "cmd not found" in parser.command_results[0].message
        )  # Match actual error message

    @pytest.mark.asyncio
    async def test_set_invalid_model_interactive(self):
        session = Session(session_id="test_session")
        state = session.state
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            preserve_unknown=False,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        await parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")]
        )
        assert session.state.backend_config.model is None
        assert not session.state.backend_config.invalid_override
        assert not parser.command_results[0].success
        assert "not available" in parser.command_results[0].message

    @pytest.mark.asyncio
    async def test_set_invalid_model_noninteractive(self):
        session = Session(session_id="test_session")
        state = session.state
        config = CommandParserConfig(
            proxy_state=state,
            app=self.mock_app,
            preserve_unknown=True,
            functional_backends=self.mock_app.state.functional_backends,
        )
        parser = CommandParser(config, command_prefix="!/")
        await parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")]
        )
        assert session.state.backend_config.backend_type is None
        assert session.state.backend_config.model is None

    @pytest.mark.asyncio
    async def test_set_backend(self):
        session = Session(session_id="test_session")
        state = session.state
        text = "!/set(backend=gemini) hi"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == "hi"
        assert session.state.backend_config.backend_type == "gemini"
        assert session.state.backend_config.model is None

    @pytest.mark.asyncio
    async def test_unset_backend(self):
        session = Session(session_id="test_session")
        state = session.state

        # Set initial backend
        new_backend_config = state.backend_config.with_backend("gemini")
        session.state = state.with_backend_config(
            cast(BackendConfiguration, new_backend_config)
        )
        assert session.state.backend_config.backend_type == "gemini"

        text = "!/unset(backend)"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            session.state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert found
        assert processed == ""
        assert session.state.backend_config.backend_type is None

    @pytest.mark.asyncio
    async def test_set_redact_api_keys_flag(self):
        session = Session(session_id="test_session")
        state = session.state
        text = "!/set(redact-api-keys-in-prompts=false)"
        processed_messages, found = await process_commands_in_messages(
            [ChatMessage(role="user", content=text)],
            state,
            app=self.mock_app,
            command_prefix="!/",
        )
        processed = processed_messages[0].content if processed_messages else ""
        assert processed == ""
        assert found
        assert not self.mock_app.state.api_key_redaction_enabled

    @pytest.mark.asyncio
    async def test_unset_redact_api_keys_flag(self):
        session = Session(session_id="test_session")
        state = session.state
        self.mock_app.state.api_key_redaction_enabled = False
        text = "!/unset(redact-api-keys-in-prompts)"
        processed_messages, found = await process_commands_in_messages(
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
