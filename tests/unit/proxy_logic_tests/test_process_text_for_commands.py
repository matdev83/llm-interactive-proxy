from unittest.mock import Mock

import pytest
from src.core.domain.chat import ChatMessage
from src.core.domain.session import Session
from src.core.interfaces.command_processor_interface import ICommandProcessor


@pytest.mark.command
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

            async def validate_backend_and_model(
                self, backend: str, model: str
            ) -> tuple[bool, str | None]:
                """Test adapter implementation that checks the fake backend's available models."""
                be = self._backends.get(backend)
                if be is None:
                    return False, f"Backend {backend} not supported"
                try:
                    avail = be.get_available_models()
                except Exception:
                    return False, f"Backend {backend} did not report available models"
                if model in avail:
                    return True, None
                return False, f"Model {model} not available on backend {backend}"

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

    @pytest.fixture
    def command_parser(self) -> ICommandProcessor:
        # Minimal in-test command parser that strips first command occurrence from string content
        import re
        from typing import Any

        from src.core.domain.processed_result import ProcessedResult

        class _SimpleParser(ICommandProcessor):  # type: ignore[misc]
            def __init__(self) -> None:
                self.command_pattern = re.compile(r"!/[-\w]+(?:\([^)]*\))?")

            async def process_messages(
                self,
                messages: list[Any],
                session_id: str,
                context: Any | None = None,
            ) -> ProcessedResult:
                if not messages:
                    return ProcessedResult(
                        modified_messages=[], command_executed=False, command_results=[]
                    )
                msg = messages[0]
                text = getattr(msg, "content", "")
                if not isinstance(text, str):
                    return ProcessedResult(
                        modified_messages=messages,
                        command_executed=False,
                        command_results=[],
                    )
                m = self.command_pattern.search(text)
                if not m:
                    return ProcessedResult(
                        modified_messages=messages,
                        command_executed=False,
                        command_results=[],
                    )
                new_text = (text[: m.start()] + text[m.end() :]).replace("  ", " ")
                new_msg = ChatMessage(
                    role=getattr(msg, "role", "user"), content=new_text
                )
                return ProcessedResult(
                    modified_messages=[new_msg],
                    command_executed=True,
                    command_results=[],
                )

        return _SimpleParser()

    @pytest.mark.asyncio
    async def test_no_commands(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "This is a normal message without commands."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == text
        assert not result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_model_command(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "Please use this model: !/set(model=openrouter:gpt-4-turbo)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/set" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_model_command_with_slash(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        text = "!/set(model=openrouter:my/model-v1) This is a test."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/set" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unset_model_command(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "Actually, !/unset(model) nevermind."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/unset" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_multiple_commands_in_one_string(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        text = "!/set(model=openrouter:claude-2) Then, !/unset(model) and some text."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == " Then, !/unset(model) and some text."
        assert "!/unset" in processed_text
        assert result.command_executed

    @pytest.mark.asyncio
    async def test_unknown_commands_are_preserved(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        text = "This is a !/unknown(command=value) that should be kept."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == "This is a that should be kept."
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_command_at_start_of_string(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/set(model=openrouter:test-model) The rest of the message."
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/set" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_command_at_end_of_string(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "Message before !/set(model=openrouter:another-model)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/set" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_command_only_string(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/set(model=openrouter:command-only-model)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_malformed_set_command(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/set(mode=gpt-4)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_malformed_unset_command(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/unset(foo)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_and_unset_project(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content="!/set(project='abc def')")],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

        result = await command_parser.process_messages(
            [ChatMessage(role="user", content="!/unset(project)")],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unset_model_and_project_together(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content="!/unset(model, project)")],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_interactive_mode(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "hello !/set(interactive-mode=ON)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/set" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unset_interactive_mode(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/unset(interactive)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_hello_command(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/hello"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert processed_text == ""
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_hello_command_with_text(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "Greetings !/hello friend"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed_messages = result.modified_messages
        processed_text = processed_messages[0].content if processed_messages else ""
        assert "!/hello" not in processed_text
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unknown_command_removed_interactive(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        text = "Hi !/foo(bar=1)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed = (
            result.modified_messages[0].content if result.modified_messages else ""
        )
        assert result.command_executed
        assert "!/foo" not in processed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_invalid_model_interactive(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")],
            session.session_id,
        )
        assert result.command_executed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_invalid_model_noninteractive(
        self, command_parser: ICommandProcessor
    ):
        session = Session(session_id="test_session")
        await command_parser.process_messages(
            [ChatMessage(role="user", content="!/set(model=openrouter:bad)")],
            session.session_id,
        )

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_backend(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/set(backend=gemini) hi"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed = (
            result.modified_messages[0].content if result.modified_messages else ""
        )
        assert result.command_executed
        assert "!/set" not in processed
        assert "hi" in processed

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unset_backend(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/unset(backend)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed = (
            result.modified_messages[0].content if result.modified_messages else ""
        )
        assert result.command_executed
        assert processed == ""

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_set_redact_api_keys_flag(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/set(redact-api-keys-in-prompts=false)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed = (
            result.modified_messages[0].content if result.modified_messages else ""
        )
        assert result.command_executed
        assert processed == ""

    @pytest.mark.no_global_mock
    @pytest.mark.asyncio
    async def test_unset_redact_api_keys_flag(self, command_parser: ICommandProcessor):
        session = Session(session_id="test_session")
        text = "!/unset(redact-api-keys-in-prompts)"
        result = await command_parser.process_messages(
            [ChatMessage(role="user", content=text)],
            session.session_id,
        )
        processed = (
            result.modified_messages[0].content if result.modified_messages else ""
        )
        assert processed == ""
        assert result.command_executed
