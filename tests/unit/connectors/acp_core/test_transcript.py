from __future__ import annotations

from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.core.domain.chat import ChatMessage


def test_transcript_serializer_empty() -> None:
    assert ACPTranscriptSerializer.serialize([]) == ""


def test_transcript_serializer_single_user_message() -> None:
    messages = [ChatMessage(role="user", content="Hello")]
    assert ACPTranscriptSerializer.serialize(messages) == "Hello"


def test_transcript_serializer_mixed_history() -> None:
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="What is 2+2?"),
        ChatMessage(role="assistant", content="4"),
        ChatMessage(role="user", content="And 3+3?"),
    ]

    result = ACPTranscriptSerializer.serialize(messages)

    assert (
        "[System Note: The user is continuing a previous session. Here is the context of what happened so far:]"
        in result
    )
    assert "**System:** You are a helpful assistant." in result
    assert "**User:** What is 2+2?" in result
    assert "**Assistant:** 4" in result
    assert "[Current Request]" in result
    assert "And 3+3?" in result


def test_transcript_serializer_with_tool_calls() -> None:
    messages = [
        {"role": "user", "content": "List files"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "list_dir", "arguments": '{"path": "."}'},
                }
            ],
        },
        {"role": "tool", "content": "file1.txt, file2.txt"},
        {"role": "user", "content": "Thanks!"},
    ]

    result = ACPTranscriptSerializer.serialize(messages)

    assert "**User:** List files" in result
    assert "**Assistant:** Let me check." in result
    assert "Tool: list_dir" in result
    assert "Input size:" in result
    assert "Output size:" in result
    assert "file1.txt" not in result
    assert "[Current Request]" in result
    assert "Thanks!" in result


def test_transcript_serializer_serialize_tail_appends_block() -> None:
    messages = [
        ChatMessage(role="user", content="first"),
        ChatMessage(role="assistant", content="second"),
        ChatMessage(role="user", content="third"),
    ]
    tail = ACPTranscriptSerializer.serialize_tail(messages, start_index=1)
    assert "Additional conversation occurred" in tail
    assert "**Assistant:** second" in tail
    assert "third" in tail


def test_transcript_serializer_serialize_tail_start_zero_delegates() -> None:
    messages = [
        ChatMessage(role="user", content="only"),
    ]
    assert ACPTranscriptSerializer.serialize_tail(
        messages, 0
    ) == ACPTranscriptSerializer.serialize(messages)
