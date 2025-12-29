"""
Artifact preview service implementation.

This module provides artifact preview expansion and compression functionality
for tool outputs, supporting the request processor's message normalization.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.domain.processed_result import ProcessedResult


@dataclass(frozen=True)
class MessageRoleAndContent:
    """Extracted role and content from a message."""

    role: Any
    content: Any


@dataclass(frozen=True)
class MessageNormalizationResult:
    """Result of message normalization with alteration flag."""

    message: Any
    altered: bool


# Artifact preview constants
_TRUNCATED_ARTIFACT_PREFIX = "<system-reminder> CRITICAL: This output was truncated."
_TRUNCATED_ARTIFACT_PATH_RE = re.compile(r"saved to ([A-Za-z]:\\[^\s]+)", re.IGNORECASE)
_EXPANDED_ARTIFACT_PREFIX = "<system-reminder> Extracted artifact from "
_ARTIFACT_MAX_LINES = 120
_ARTIFACT_MAX_CHARS = 6000
_COMPRESSED_ARTIFACT_MAX_LINES = 40
_COMPRESSED_ARTIFACT_MAX_CHARS = 1500

logger = logging.getLogger(__name__)


class ArtifactService:
    """
    Service for handling artifact preview expansion and compression.

    Implements the IArtifactService interface for managing tool output
    artifact references and previews.
    """

    def normalize_artifact_previews(self, processed_result: ProcessedResult) -> None:
        """
        Expand and compress artifact previews in tool outputs.

        This method modifies the processed_result in-place:
        - Expands truncated artifact previews in the most recent tool message batch
        - Compresses older expanded previews to preserve context window

        All operations are fail-open (skip on errors, missing paths, etc.).
        """
        messages = getattr(processed_result, "modified_messages", None)
        if not messages:
            return

        normalized_messages: list[Any] = list(messages)
        changed = False

        tail_indices = self._identify_trailing_tool_indices(messages)
        tail_index_set = set(tail_indices)

        # First, compress previously expanded previews outside the current tool batch
        for idx, raw_message in enumerate(messages):
            if idx in tail_index_set:
                continue
            result = self._compress_existing_artifact_preview(raw_message)
            if result.altered:
                normalized_messages[idx] = result.message
                changed = True

        # Then expand truncated outputs for the most recent tool batch
        for idx in tail_indices:
            raw_message = normalized_messages[idx]
            result = self._normalize_tool_message(raw_message)
            if result.altered:
                normalized_messages[idx] = result.message
                changed = True

        if changed:
            processed_result.modified_messages = normalized_messages

    def _normalize_tool_message(self, raw_message: Any) -> MessageNormalizationResult:
        """Return tool message with expanded artifact content when possible."""
        role_content = self._get_message_role_and_content(raw_message)

        if role_content.role != "tool":
            return MessageNormalizationResult(message=raw_message, altered=False)

        replacement = self._extract_truncated_artifact_preview(role_content.content)
        if replacement is None:
            return MessageNormalizationResult(message=raw_message, altered=False)

        if isinstance(raw_message, dict):
            updated = dict(raw_message)
            updated["content"] = replacement
            return MessageNormalizationResult(message=updated, altered=True)

        if hasattr(raw_message, "model_copy"):
            return MessageNormalizationResult(
                message=raw_message.model_copy(update={"content": replacement}),
                altered=True,
            )

        # Fallback: attempt in-place assignment
        try:
            raw_message.content = replacement  # type: ignore[attr-defined]
            return MessageNormalizationResult(message=raw_message, altered=True)
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to assign content in-place for tool message normalization",
                    exc_info=True,
                )
            return MessageNormalizationResult(message=raw_message, altered=False)

    def _compress_existing_artifact_preview(
        self, raw_message: Any
    ) -> MessageNormalizationResult:
        """Trim previously expanded artifact previews to keep history compact."""
        role_content = self._get_message_role_and_content(raw_message)
        if role_content.role != "tool" or not isinstance(role_content.content, str):
            return MessageNormalizationResult(message=raw_message, altered=False)

        content = role_content.content
        if not content.startswith(_EXPANDED_ARTIFACT_PREFIX):
            return MessageNormalizationResult(message=raw_message, altered=False)

        summary = self._build_artifact_summary(content)
        if summary is None:
            return MessageNormalizationResult(message=raw_message, altered=False)

        if isinstance(raw_message, dict):
            updated = dict(raw_message)
            updated["content"] = summary
            return MessageNormalizationResult(message=updated, altered=True)

        if hasattr(raw_message, "model_copy"):
            return MessageNormalizationResult(
                message=raw_message.model_copy(update={"content": summary}),
                altered=True,
            )

        try:
            raw_message.content = summary  # type: ignore[attr-defined]
            return MessageNormalizationResult(message=raw_message, altered=True)
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to assign content in-place for artifact preview compression",
                    exc_info=True,
                )
            return MessageNormalizationResult(message=raw_message, altered=False)

    def _get_message_role_and_content(self, raw_message: Any) -> MessageRoleAndContent:
        """Extract role and content from dicts or objects uniformly."""
        if isinstance(raw_message, dict):
            return MessageRoleAndContent(
                role=raw_message.get("role"),
                content=raw_message.get("content"),
            )
        return MessageRoleAndContent(
            role=getattr(raw_message, "role", None),
            content=getattr(raw_message, "content", None),
        )

    def _extract_truncated_artifact_preview(self, content: Any) -> str | None:
        """Extract and truncate the artifact referenced by the tool output."""
        if not isinstance(content, str):
            return None
        if _TRUNCATED_ARTIFACT_PREFIX not in content:
            return None

        match = _TRUNCATED_ARTIFACT_PATH_RE.search(content)
        if not match:
            return None

        raw_path = match.group(1)
        artifact_path = self._convert_artifact_path(raw_path)
        if artifact_path is None or not artifact_path.exists():
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Artifact path %s could not be resolved or does not exist", raw_path
                )
            return None

        try:
            artifact_text = artifact_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to read tool artifact %s: %s", artifact_path, exc
                )
            return None

        preview = self._build_artifact_preview(artifact_text)
        note = (
            f"<system-reminder> Extracted artifact from {raw_path}. "
            "Showing limited preview for the language model.\n\n"
        )
        return note + preview

    def _convert_artifact_path(self, raw_path: str) -> Path | None:
        """Convert CLI artifact path to a path accessible from this environment."""
        potential_path = Path(raw_path)
        if potential_path.exists():
            return potential_path

        # Handle Windows paths when running under WSL/Linux (e.g., C:\ -> /mnt/c/)
        if len(raw_path) > 2 and raw_path[1:3] == ":\\":
            drive = raw_path[0].lower()
            remainder = raw_path[3:].replace("\\", "/")
            candidate = Path(f"/mnt/{drive}/{remainder}")
            if candidate.exists():
                return candidate

        return None

    def _build_artifact_preview(self, artifact_text: str) -> str:
        """Produce a trimmed preview of artifact contents."""
        lines = artifact_text.splitlines()
        truncated_lines = False

        if len(lines) > _ARTIFACT_MAX_LINES:
            omitted = len(lines) - _ARTIFACT_MAX_LINES
            lines = lines[:_ARTIFACT_MAX_LINES]
            lines.append(f"[... {omitted} additional lines omitted ...]")
            truncated_lines = True

        preview = "\n".join(lines)

        if len(preview) > _ARTIFACT_MAX_CHARS:
            preview = preview[:_ARTIFACT_MAX_CHARS] + "\n[... output truncated ...]"
            truncated_lines = True

        if truncated_lines:
            preview += "\n"

        return preview

    def _identify_trailing_tool_indices(self, messages: list[Any]) -> list[int]:
        """Return indices of contiguous trailing tool messages."""
        indices: list[int] = []
        for index in range(len(messages) - 1, -1, -1):
            role_content = self._get_message_role_and_content(messages[index])
            role = role_content.role
            if role != "tool":
                break
            indices.append(index)
        indices.reverse()
        return indices

    def _build_artifact_summary(self, content: str) -> str | None:
        """Create a compact summary placeholder for an expanded artifact preview."""
        raw_path = self._extract_path_from_expanded_preview(content)
        header_path = raw_path or "the previous artifact"
        header = (
            f"<system-reminder> Artifact preview trimmed to preserve context: {header_path}. "
            "Use the read command with this path if additional detail is required.\n\n"
        )

        _, body = self._split_expanded_artifact_preview(content)
        snippet, truncated = self._build_compressed_preview(body)
        if not snippet:
            return header.rstrip()

        if truncated and not snippet.endswith("\n"):
            snippet += "\n"
        if truncated:
            snippet += "[... additional content omitted ...]"

        return header + snippet

    def _extract_path_from_expanded_preview(self, content: str) -> str | None:
        """Parse the artifact path from an expanded preview string."""
        if not content.startswith(_EXPANDED_ARTIFACT_PREFIX):
            return None
        remainder = content[len(_EXPANDED_ARTIFACT_PREFIX) :]
        marker = ". Showing limited preview"
        marker_index = remainder.find(marker)
        if marker_index == -1:
            return None
        return remainder[:marker_index].strip()

    def _split_expanded_artifact_preview(self, content: str) -> tuple[str, str]:
        """Split expanded artifact preview into header and body segments."""
        if not isinstance(content, str):
            return "", ""

        double_newline = "\n\n"
        parts = content.split(double_newline, 1)
        if len(parts) == 2:
            return parts[0] + double_newline, parts[1]
        newline_index = content.find("\n")
        if newline_index == -1:
            return content, ""
        return content[: newline_index + 1], content[newline_index + 1 :]

    def _build_compressed_preview(self, text: str) -> tuple[str, bool]:
        """Return aggressively truncated preview text with truncation flag."""
        if not text:
            return "", False

        lines = text.splitlines()
        truncated = False
        if len(lines) > _COMPRESSED_ARTIFACT_MAX_LINES:
            lines = lines[:_COMPRESSED_ARTIFACT_MAX_LINES]
            truncated = True

        preview = "\n".join(lines)

        if len(preview) > _COMPRESSED_ARTIFACT_MAX_CHARS:
            preview = preview[:_COMPRESSED_ARTIFACT_MAX_CHARS]
            truncated = True

        return preview, truncated
