"""Tests for truncated tool output expansion logic in RequestProcessor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from src.core.domain.processed_result import ProcessedResult
from src.core.services.request_processor_service import (
    _EXPANDED_ARTIFACT_PREFIX,
    _TRUNCATED_ARTIFACT_PREFIX,
    RequestProcessor,
)


def _build_processor() -> RequestProcessor:
    """Create a RequestProcessor with minimal mocked dependencies."""
    return RequestProcessor(
        command_processor=MagicMock(),
        session_manager=MagicMock(),
        backend_request_manager=MagicMock(),
        response_manager=MagicMock(),
    )


def test_expand_truncated_outputs_limits_history_growth(tmp_path: Path) -> None:
    """Ensure only the latest truncated outputs are expanded and older previews are compacted."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    artifact_path = artifacts_dir / "latest.txt"
    artifact_path.write_text("line 1\nline 2\nline 3\n")

    raw_prev_path = r"C:\Users\Test\artifact_prev.txt"
    raw_new_path = r"C:\Users\Test\artifact_new.txt"

    previous_preview = (
        f"{_EXPANDED_ARTIFACT_PREFIX}{raw_prev_path}. Showing limited preview for the language model.\n\n"
        "old preview line"
    )
    truncated_tail = (
        f"{_TRUNCATED_ARTIFACT_PREFIX} Additional output saved to {raw_new_path} for later inspection."
    )

    processed = ProcessedResult(
        modified_messages=[
            {"role": "assistant", "content": "Earlier reasoning step"},
            {"role": "tool", "content": previous_preview},
            {"role": "user", "content": "Please continue"},
            {"role": "assistant", "content": "Calling read tool"},
            {"role": "tool", "content": truncated_tail},
        ],
        command_executed=True,
        command_results=[],
    )

    processor = _build_processor()
    processor._convert_artifact_path = MagicMock(
        side_effect=lambda path: artifact_path if path == raw_new_path else None
    )

    processor._expand_truncated_tool_outputs(processed)

    updated_messages = processed.modified_messages
    assert updated_messages[1]["content"].startswith(
        "<system-reminder> Artifact preview trimmed to preserve context"
    )
    assert raw_prev_path in updated_messages[1]["content"]
    assert "old preview line" in updated_messages[1]["content"]

    latest_content = updated_messages[-1]["content"]
    assert latest_content.startswith(_EXPANDED_ARTIFACT_PREFIX)
    assert "line 1" in latest_content
    assert processor._convert_artifact_path.call_count == 1
