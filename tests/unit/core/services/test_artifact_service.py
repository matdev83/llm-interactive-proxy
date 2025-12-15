"""
Tests for ArtifactService implementation.

These tests verify artifact preview expansion and compression behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.domain.chat import ChatMessage
from src.core.domain.processed_result import ProcessedResult
from src.core.services.artifact_service import ArtifactService


@pytest.fixture
def artifact_service() -> ArtifactService:
    """Create an artifact service instance."""
    return ArtifactService()


def test_normalize_artifact_previews_no_messages(
    artifact_service: ArtifactService,
) -> None:
    """Test that normalize_artifact_previews handles empty modified_messages."""
    processed_result = ProcessedResult(
        modified_messages=[],
        command_executed=False,
        command_results=[],
    )
    # Set to None to test edge case
    processed_result.modified_messages = None  # type: ignore[assignment]

    # Should not raise, should handle gracefully
    artifact_service.normalize_artifact_previews(processed_result)

    # Should not modify the processed_result
    assert processed_result.modified_messages is None


def test_normalize_artifact_previews_no_tool_messages(
    artifact_service: ArtifactService,
) -> None:
    """Test that normalize_artifact_previews ignores non-tool messages."""
    messages = [
        ChatMessage(role="user", content="Hello"),
        ChatMessage(role="assistant", content="Hi there!"),
    ]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=False,
        command_results=[],
    )

    artifact_service.normalize_artifact_previews(processed_result)

    # Should not modify messages
    assert processed_result.modified_messages == messages


def test_normalize_artifact_previews_expands_truncated_artifact(
    artifact_service: ArtifactService,
    tmp_path: Path,
) -> None:
    """Test that truncated artifacts are expanded from file references."""
    # Create a test artifact file
    artifact_file = tmp_path / "test_output.txt"
    artifact_content = "Line 1\nLine 2\nLine 3\n"
    artifact_file.write_text(artifact_content, encoding="utf-8")

    # Create a tool message with truncation marker
    tool_message = {
        "role": "tool",
        "content": (
            f"<system-reminder> CRITICAL: This output was truncated. "
            f"Full content saved to {artifact_file}"
        ),
    }

    messages = [ChatMessage(role="user", content="read file"), tool_message]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    artifact_service.normalize_artifact_previews(processed_result)

    # Verify the artifact was expanded
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None
    assert len(modified_messages) == 2

    # Check that the tool message now contains the artifact content
    tool_msg = modified_messages[1]
    content = (
        tool_msg.get("content") if isinstance(tool_msg, dict) else tool_msg.content
    )
    assert isinstance(content, str)
    assert "Extracted artifact from" in content
    # Check that the artifact content is present (may have trailing newline stripped)
    assert "Line 1" in content
    assert "Line 2" in content
    assert "Line 3" in content


def test_normalize_artifact_previews_compresses_old_previews(
    artifact_service: ArtifactService,
) -> None:
    """Test that old expanded previews are compressed to save context."""
    # Create an expanded preview message (old)
    old_preview = {
        "role": "tool",
        "content": (
            "<system-reminder> Extracted artifact from C:\\output.txt. "
            "Showing limited preview for the language model.\n\n"
            + ("Line content\n" * 50)  # Long content
        ),
    }

    # Create a new tool message (trailing)
    new_tool_message = {
        "role": "tool",
        "content": "New tool output",
    }

    messages = [
        ChatMessage(role="user", content="read file"),
        old_preview,
        ChatMessage(role="user", content="another command"),
        new_tool_message,
    ]

    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    artifact_service.normalize_artifact_previews(processed_result)

    # Verify the old preview was compressed
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None

    # The old preview (index 1) should be compressed
    old_msg = modified_messages[1]
    content = old_msg.get("content") if isinstance(old_msg, dict) else old_msg.content
    assert isinstance(content, str)
    assert "Artifact preview trimmed to preserve context" in content
    # Should be much shorter than original (50 * 13 = 650 chars original)
    # Compressed should be around 40 lines * avg line length + header
    assert len(content) < 900  # Reasonable limit for compressed preview


def test_normalize_artifact_previews_handles_missing_file(
    artifact_service: ArtifactService,
) -> None:
    """Test that missing artifact files don't cause errors."""
    tool_message = {
        "role": "tool",
        "content": (
            "<system-reminder> CRITICAL: This output was truncated. "
            "Full content saved to C:\\nonexistent\\file.txt"
        ),
    }

    messages = [ChatMessage(role="user", content="read file"), tool_message]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    # Should not raise, should handle gracefully
    artifact_service.normalize_artifact_previews(processed_result)

    # Message should remain unchanged
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None
    assert len(modified_messages) == 2
    assert modified_messages[1] == tool_message


def test_normalize_artifact_previews_handles_read_error(
    artifact_service: ArtifactService,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that file read errors don't cause failures."""
    # Create a file but make it unreadable by mocking Path.read_text
    artifact_file = tmp_path / "test_output.txt"
    artifact_file.write_text("content", encoding="utf-8")

    def mock_read_text(*args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", mock_read_text)

    tool_message = {
        "role": "tool",
        "content": (
            f"<system-reminder> CRITICAL: This output was truncated. "
            f"Full content saved to {artifact_file}"
        ),
    }

    messages = [ChatMessage(role="user", content="read file"), tool_message]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    # Should not raise, should handle gracefully
    artifact_service.normalize_artifact_previews(processed_result)

    # Message should remain unchanged
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None
    assert modified_messages[1] == tool_message


def test_normalize_artifact_previews_respects_max_lines(
    artifact_service: ArtifactService,
    tmp_path: Path,
) -> None:
    """Test that artifact previews are truncated to max lines limit."""
    # Create a file with many lines
    artifact_file = tmp_path / "long_output.txt"
    lines = [f"Line {i}\n" for i in range(200)]
    artifact_file.write_text("".join(lines), encoding="utf-8")

    tool_message = {
        "role": "tool",
        "content": (
            f"<system-reminder> CRITICAL: This output was truncated. "
            f"Full content saved to {artifact_file}"
        ),
    }

    messages = [ChatMessage(role="user", content="read file"), tool_message]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    artifact_service.normalize_artifact_previews(processed_result)

    # Verify truncation occurred
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None
    tool_msg = modified_messages[1]
    content = (
        tool_msg.get("content") if isinstance(tool_msg, dict) else tool_msg.content
    )
    assert isinstance(content, str)
    assert "additional lines omitted" in content


def test_normalize_artifact_previews_supports_pydantic_messages(
    artifact_service: ArtifactService,
    tmp_path: Path,
) -> None:
    """Test that Pydantic message models are supported."""
    artifact_file = tmp_path / "test_output.txt"
    artifact_file.write_text("Test content", encoding="utf-8")

    # Use Pydantic ChatMessage model
    tool_message = ChatMessage(
        role="tool",
        content=(
            f"<system-reminder> CRITICAL: This output was truncated. "
            f"Full content saved to {artifact_file}"
        ),
    )

    messages = [ChatMessage(role="user", content="read file"), tool_message]
    processed_result = ProcessedResult(
        modified_messages=messages,
        command_executed=True,
        command_results=[],
    )

    artifact_service.normalize_artifact_previews(processed_result)

    # Verify it worked with Pydantic models
    modified_messages = processed_result.modified_messages
    assert modified_messages is not None
    assert len(modified_messages) == 2

    tool_msg = modified_messages[1]
    assert isinstance(tool_msg, ChatMessage)
    assert isinstance(tool_msg.content, str)
    assert "Extracted artifact from" in tool_msg.content
