"""Deterministic tool event collector for ProxyMem.

Collects file edits and git commits from proxy tool hooks,
normalizes paths, and deduplicates per session.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from src.core.memory.models import FileEditEvent, GitCommitEvent, ToolEvent

logger = logging.getLogger(__name__)


class DeterministicToolEventCollector:
    """Tracks deterministic file edits and git commits per session.

    Collects tool events emitted by the proxy's tool hooks, normalizes
    file paths relative to the project root, and deduplicates entries.
    """

    def __init__(self) -> None:
        """Initialize the collector."""
        # session_id -> path -> latest FileEditEvent
        self._file_edits: dict[str, dict[str, FileEditEvent]] = defaultdict(dict)
        # session_id -> list of GitCommitEvent (deduped by hash)
        self._git_commits: dict[str, list[GitCommitEvent]] = defaultdict(list)
        # session_id -> set of commit hashes (for dedup)
        self._commit_hashes: dict[str, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def record_file_edit(
        self,
        session_id: str,
        event: FileEditEvent,
        project_root: str | None,
    ) -> None:
        """Record a file edit event for a session.

        Normalizes the path relative to project_root when provided;
        deduplicates by path, keeping the most recent event.

        Args:
            session_id: The session identifier.
            event: The file edit event to record.
            project_root: Optional project root for path normalization.
        """
        normalized_path = self._normalize_path(event.path, project_root)

        async with self._lock:
            session_edits = self._file_edits[session_id]

            # Create normalized event
            normalized_event = FileEditEvent(
                path=normalized_path,
                action=event.action,
                tool=event.tool,
                timestamp=event.timestamp,
            )

            # Keep the most recent event per path
            existing = session_edits.get(normalized_path)
            if existing is None or event.timestamp > existing.timestamp:
                session_edits[normalized_path] = normalized_event
                logger.debug(
                    "Recorded file edit for session %s: %s (%s)",
                    session_id,
                    normalized_path,
                    event.action,
                )

    async def record_git_commit(
        self,
        session_id: str,
        event: GitCommitEvent,
    ) -> None:
        """Record a git commit event for a session.

        Deduplicates by commit hash within the session.

        Args:
            session_id: The session identifier.
            event: The git commit event to record.
        """
        async with self._lock:
            # Check for duplicate by hash
            if event.commit_hash in self._commit_hashes[session_id]:
                logger.debug(
                    "Duplicate commit hash %s for session %s, skipping",
                    event.commit_hash,
                    session_id,
                )
                return

            self._git_commits[session_id].append(event)
            self._commit_hashes[session_id].add(event.commit_hash)
            logger.debug(
                "Recorded git commit for session %s: %s",
                session_id,
                event.commit_hash[:8],
            )

    async def record_tool_event(
        self,
        session_id: str,
        event: ToolEvent,
        project_root: str | None = None,
    ) -> None:
        """Record a tool event (file edit or git commit) for a session.

        Dispatches to the appropriate handler based on event type.

        Args:
            session_id: The session identifier.
            event: The tool event to record.
            project_root: Optional project root for file path normalization.
        """
        if isinstance(event, FileEditEvent):
            await self.record_file_edit(session_id, event, project_root)
        elif isinstance(event, GitCommitEvent):
            await self.record_git_commit(session_id, event)
        else:
            logger.warning("Unknown tool event type: %s", type(event).__name__)

    async def get_and_clear(
        self,
        session_id: str,
    ) -> tuple[list[FileEditEvent], list[GitCommitEvent]]:
        """Get and clear all tool events for a session.

        Returns:
            Tuple of (file_edits, git_commits).
        """
        async with self._lock:
            # Get file edits (sorted by path for consistency)
            file_edits = list(self._file_edits.pop(session_id, {}).values())
            file_edits.sort(key=lambda e: e.path)

            # Get git commits (already in chronological order)
            git_commits = self._git_commits.pop(session_id, [])

            # Clean up hash tracking
            self._commit_hashes.pop(session_id, None)

            logger.debug(
                "Retrieved %d file edits and %d git commits for session %s",
                len(file_edits),
                len(git_commits),
                session_id,
            )

            return file_edits, git_commits

    async def get_file_edit_count(self, session_id: str) -> int:
        """Get the number of file edits recorded for a session."""
        async with self._lock:
            return len(self._file_edits.get(session_id, {}))

    async def get_git_commit_count(self, session_id: str) -> int:
        """Get the number of git commits recorded for a session."""
        async with self._lock:
            return len(self._git_commits.get(session_id, []))

    async def has_session(self, session_id: str) -> bool:
        """Check if events exist for a session."""
        async with self._lock:
            return session_id in self._file_edits or session_id in self._git_commits

    async def clear_session(self, session_id: str) -> None:
        """Clear all events for a session without returning them."""
        async with self._lock:
            self._file_edits.pop(session_id, None)
            self._git_commits.pop(session_id, None)
            self._commit_hashes.pop(session_id, None)

    def _normalize_path(self, path: str, project_root: str | None) -> str:
        """Normalize a file path.

        When project_root is provided, attempts to make the path relative.
        Always uses forward slashes for consistency.

        Args:
            path: The file path to normalize.
            project_root: Optional project root directory.

        Returns:
            Normalized path string.
        """
        # Always use forward slashes
        normalized = path.replace("\\", "/")

        if not project_root:
            return normalized

        # Normalize project root
        root = project_root.replace("\\", "/").rstrip("/")

        # Try to make path relative
        try:
            # Handle case-insensitive path comparison on Windows
            normalized_lower = normalized.lower()
            root_lower = root.lower() + "/"

            if normalized_lower.startswith(root_lower):
                # Extract relative path preserving original case
                relative = normalized[len(root) + 1 :]
                return relative if relative else normalized
        except (ValueError, TypeError):
            pass

        # If we can't make it relative, return as-is with forward slashes
        return normalized

    @staticmethod
    def classify_action_from_tool(tool_name: str) -> str:
        """Classify the file action based on tool name.

        Args:
            tool_name: The name of the tool that performed the edit.

        Returns:
            Action classification: "created", "modified", "deleted", or "unknown".
        """
        tool_lower = tool_name.lower() if tool_name else ""

        # Common patterns for create operations
        create_patterns = ["create", "write_to_file", "new_file", "touch"]
        for pattern in create_patterns:
            if pattern in tool_lower:
                return "created"

        # Common patterns for modify operations
        modify_patterns = [
            "patch",
            "edit",
            "modify",
            "replace",
            "append",
            "update",
            "multi_replace",
        ]
        for pattern in modify_patterns:
            if pattern in tool_lower:
                return "modified"

        # Common patterns for delete operations
        delete_patterns = ["delete", "remove", "rm", "unlink"]
        for pattern in delete_patterns:
            if pattern in tool_lower:
                return "deleted"

        # Default to "modified" for unknown file-editing tools
        # as it's the safest assumption
        return "unknown"
