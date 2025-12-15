import pytest
from src.core.commands.pipeline.tail_extractor import CommandTailExtractor
from src.core.domain.chat import ChatMessage, MessageContentPartText


class TestCommandTailExtractor:
    @pytest.fixture
    def extractor(self) -> CommandTailExtractor:
        return CommandTailExtractor()

    def test_extracts_last_non_blank_line_from_string_message(
        self, extractor: CommandTailExtractor
    ) -> None:
        messages = [
            ChatMessage(role="user", content="Hello there"),
            ChatMessage(
                role="user",
                content="Some context\n\n   !/set(model=openrouter:gpt-4)   ",
            ),
        ]

        result = extractor.extract_tail_segment(messages)

        assert result.content == "!/set(model=openrouter:gpt-4)"
        assert result.message_index == 1
        assert result.part_index is None

    def test_extracts_tail_from_structured_message_parts(
        self, extractor: CommandTailExtractor
    ) -> None:
        messages = [
            ChatMessage(role="assistant", content="Sure thing!"),
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(text="Notes:"),
                    MessageContentPartText(text="   \n!/unset(model)\n"),
                ],
            ),
        ]

        result = extractor.extract_tail_segment(messages)

        assert result.content == "!/unset(model)"
        assert result.message_index == 1
        assert result.part_index == 1

    def test_returns_empty_result_when_no_user_message(
        self, extractor: CommandTailExtractor
    ) -> None:
        messages = [
            ChatMessage(role="assistant", content="How can I help?"),
        ]

        result = extractor.extract_tail_segment(messages)

        assert result.content == ""
        assert result.message_index is None
        assert result.part_index is None

    def test_ignores_prior_user_messages_when_latest_has_no_content(
        self, extractor: CommandTailExtractor
    ) -> None:
        messages = [
            ChatMessage(role="user", content="!/set(temperature=0.7)"),
            ChatMessage(role="assistant", content="Acknowledged."),
            ChatMessage(role="user", content=None),
        ]

        result = extractor.extract_tail_segment(messages)

        assert result.content == ""
        assert result.message_index == 2
        assert result.part_index is None
