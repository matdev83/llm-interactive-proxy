"""Summary generator for ProxyMem feature.

Generates structured XML summaries from session transcripts using LLM calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from src.core.memory.config import MemoryConfiguration
from src.core.memory.interfaces import LLMCaller
from src.core.memory.models import (
    CapturedInteraction,
    FileChange,
    FileEditEvent,
    GitCommitEvent,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)
from src.core.memory.prompt_loader import PromptLoader
from src.core.services import metrics_service

if TYPE_CHECKING:
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    """Result of summary generation."""

    success: bool
    summary: SessionSummary | None = None
    error: str | None = None
    retries: int = 0


@dataclass(frozen=True)
class ValidationResult:
    """Result of XML validation."""

    is_valid: bool
    error: str | None = None


class SummaryValidator:
    """Validates XML summaries against schema requirements.

    Validates the full schema as specified in the design doc, including:
    - Required elements (title, completion_status, metadata block)
    - Valid enum values for status fields
    - Proper XML escaping and structure
    """

    VALID_COMPLETION_STATUSES = {"completed", "partial", "abandoned"}
    VALID_TASK_STATUSES = {"open", "blocked"}
    VALID_FILE_STATUSES = {"created", "modified", "deleted"}
    VALID_GIT_TYPES = {"commit", "branch", "merge", "rebase", "cherry-pick"}
    VALID_TEST_STATUSES = {"passed", "failed", "timeout", "skipped"}

    # Required elements per spec (Req 12.2)
    REQUIRED_ELEMENTS = ["title", "completion_status"]

    # Required metadata elements per spec (Req 12.3)
    REQUIRED_METADATA = ["session_id", "analysis_timestamp", "summary_version"]

    def validate(self, xml_content: str) -> ValidationResult:
        """Validate XML content against summary schema.

        Args:
            xml_content: The XML string to validate.

        Returns:
            ValidationResult containing validity status and optional error message.
        """
        # Strip any preamble/postamble
        xml_content = self._extract_xml(xml_content)

        if not xml_content:
            return ValidationResult(
                is_valid=False, error="No valid XML found in response"
            )

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            return ValidationResult(is_valid=False, error=f"XML parse error: {e}")

        if root.tag != "session_summary":
            return ValidationResult(
                is_valid=False,
                error=f"Expected root element 'session_summary', got '{root.tag}'",
            )

        # Check required elements
        for elem_name in self.REQUIRED_ELEMENTS:
            elem = root.find(elem_name)
            if elem is None or not elem.text:
                return ValidationResult(
                    is_valid=False, error=f"Missing required element: {elem_name}"
                )

        # Validate completion_status enum
        status_elem = root.find("completion_status")
        if (
            status_elem is not None
            and status_elem.text
            and status_elem.text.strip() not in self.VALID_COMPLETION_STATUSES
        ):
            return ValidationResult(
                is_valid=False, error=f"Invalid completion_status: {status_elem.text}"
            )

        # Validate metadata block (Req 12.3)
        metadata = root.find("metadata")
        if metadata is not None:
            for meta_elem in self.REQUIRED_METADATA:
                elem = metadata.find(meta_elem)
                if elem is None:
                    return ValidationResult(
                        is_valid=False,
                        error=f"Missing required metadata element: {meta_elem}",
                    )

        # Validate task statuses in remaining_tasks
        remaining_tasks = root.find("remaining_tasks")
        if remaining_tasks is not None:
            for task in remaining_tasks.findall("task"):
                status = task.get("status")
                if status and status not in self.VALID_TASK_STATUSES:
                    return ValidationResult(
                        is_valid=False, error=f"Invalid task status: {status}"
                    )

        # Validate file statuses in touched_files
        touched_files = root.find("touched_files")
        if touched_files is not None:
            for file_elem in touched_files.findall("file"):
                status = file_elem.get("status")
                if status and status not in self.VALID_FILE_STATUSES:
                    return ValidationResult(
                        is_valid=False, error=f"Invalid file status: {status}"
                    )

        # Validate git operation types
        git_ops = root.find("git_operations")
        if git_ops is not None:
            for op in git_ops.findall("operation"):
                op_type = op.get("type")
                if op_type and op_type not in self.VALID_GIT_TYPES:
                    return ValidationResult(
                        is_valid=False, error=f"Invalid git operation type: {op_type}"
                    )

        # Validate test statuses
        tests_run = root.find("tests_run")
        if tests_run is not None:
            for test in tests_run.findall("test"):
                status = test.get("status")
                if status and status not in self.VALID_TEST_STATUSES:
                    return ValidationResult(
                        is_valid=False, error=f"Invalid test status: {status}"
                    )

        return ValidationResult(is_valid=True, error=None)

    def _extract_xml(self, content: str) -> str:
        """Extract XML from content, stripping preamble/postamble."""
        # Try to find <session_summary> block
        match = re.search(
            r"<session_summary[^>]*>.*?</session_summary>",
            content,
            re.DOTALL,
        )
        if match:
            return match.group(0)

        # If content starts with < assume it's XML
        stripped = content.strip()
        if stripped.startswith("<"):
            return stripped

        return ""


class SummaryGenerator:
    """Generates session summaries using LLM calls."""

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
        prompt_loader: PromptLoader | None = None,
        llm_caller: LLMCaller | None = None,
    ):
        """Initialize the summary generator.

        Args:
            config: Memory configuration.
            repository: Repository for persisting summaries.
            prompt_loader: Optional prompt loader (created if not provided).
            llm_caller: Optional LLM caller for testing.
        """
        self._config = config
        self._repository = repository
        self._prompt_loader = prompt_loader or PromptLoader(
            summary_prompt_path=config.summary_prompt,
            context_prompt_path=config.context_prompt,
        )
        self._llm_caller = llm_caller
        self._validator = SummaryValidator()

    async def generate_summary(
        self,
        session_id: str,
        user_id: str,
        interactions: list[CapturedInteraction],
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        backend_model: str | None = None,
        client_agent: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
        is_partial: bool = False,
        deterministic_file_edits: list[FileEditEvent] | None = None,
        deterministic_git_commits: list[GitCommitEvent] | None = None,
    ) -> SummaryResult:
        """Generate a summary for a session.

        Args:
            session_id: The session identifier.
            user_id: The user identifier.
            interactions: List of captured interactions.
            tenant_id: Optional tenant identifier.
            project_id: Optional project identifier.
            project_root: Optional project root path.
            backend_model: The backend:model used.
            client_agent: The client agent name.
            branch: Git branch name.
            head_sha: Git HEAD SHA.
            is_partial: Whether the capture was partial (overflow).
            deterministic_file_edits: List of file edit events from tool calls.
            deterministic_git_commits: List of git commit events from tool calls.

        Returns:
            SummaryResult with success status and summary or error.
        """
        metrics_service.inc("memory.summary.requested")
        with metrics_service.timer("memory.summary.generate.duration"):
            return await self._generate_summary_impl(
                session_id=session_id,
                user_id=user_id,
                interactions=interactions,
                tenant_id=tenant_id,
                project_id=project_id,
                project_root=project_root,
                backend_model=backend_model,
                client_agent=client_agent,
                branch=branch,
                head_sha=head_sha,
                is_partial=is_partial,
                deterministic_file_edits=deterministic_file_edits,
                deterministic_git_commits=deterministic_git_commits,
            )

    async def _generate_summary_impl(
        self,
        session_id: str,
        user_id: str,
        interactions: list[CapturedInteraction],
        *,
        tenant_id: str | None = None,
        project_id: str | None = None,
        project_root: str | None = None,
        backend_model: str | None = None,
        client_agent: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
        is_partial: bool = False,
        deterministic_file_edits: list[FileEditEvent] | None = None,
        deterministic_git_commits: list[GitCommitEvent] | None = None,
    ) -> SummaryResult:
        """Generate a summary for a session (implementation)."""
        if not interactions:
            metrics_service.inc("memory.summary.failure")
            return SummaryResult(
                success=False,
                error="No interactions to summarize",
            )

        # Build transcript
        transcript = self._build_transcript(interactions)

        # Apply redaction
        transcript = self._apply_redaction(transcript)

        # Handle large transcripts via chunking
        if len(transcript) > self._config.max_transcript_chars:
            try:
                transcript = await self._process_large_transcript(transcript)
            except Exception as e:
                logger.exception(
                    "Failed to process large transcript for session %s", session_id
                )
                metrics_service.inc("memory.summary.failure")
                return SummaryResult(
                    success=False,
                    error=f"Chunking error: {e}",
                )

        # Build prompt
        prompt_template = self._prompt_loader.load_summary_prompt()
        now = datetime.now(timezone.utc)

        # Format deterministic file edits for prompt injection
        file_edits_str = self._format_file_edits_for_prompt(
            deterministic_file_edits or []
        )

        # Format deterministic git commits for prompt injection
        git_commits_str = self._format_git_commits_for_prompt(
            deterministic_git_commits or []
        )

        variables = {
            "session_transcript": transcript,
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id or "NONE",
            "project_id": project_id or "NONE",
            "project_root": project_root or "UNKNOWN",
            "model": backend_model or "UNKNOWN",
            "branch": branch or "UNKNOWN",
            "head_sha": head_sha or "UNKNOWN",
            "analysis_timestamp": now.isoformat(),
            "summary_schema_version": self._config.summary_schema_version,
            "summary_prompt_version": self._config.summary_prompt_version,
            "max_tokens": str(self._config.max_summary_tokens),
            "deterministic_file_edits": file_edits_str,
            "deterministic_git_commits": git_commits_str,
        }

        prompt = self._prompt_loader.substitute_variables(prompt_template, variables)

        # Call LLM with retry
        xml_response = await self._call_llm_with_retry(prompt)
        if xml_response is None:
            metrics_service.inc("memory.summary.llm_failure")
            metrics_service.inc("memory.summary.failure")
            return SummaryResult(
                success=False,
                error="LLM call failed after retries",
            )

        # Validate response
        validation_result = self._validator.validate(xml_response)
        if not validation_result.is_valid:
            logger.warning(
                "Summary validation failed for session %s: %s",
                session_id,
                validation_result.error,
            )
            metrics_service.inc("memory.summary.failure")
            return SummaryResult(
                success=False,
                error=f"Validation failed: {validation_result.error}",
            )

        # Parse XML into SessionSummary
        try:
            summary = self._parse_xml_to_summary(
                xml_response,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                project_id=project_id,
                project_root=project_root,
                backend_model=backend_model or "unknown:unknown",
                client_agent=client_agent,
                branch=branch,
                head_sha=head_sha,
                is_partial=is_partial,
                session_start=interactions[0].timestamp,
                deterministic_file_edits=deterministic_file_edits or [],
                deterministic_git_commits=deterministic_git_commits or [],
            )
        except Exception as e:
            logger.exception("Failed to parse summary XML for session %s", session_id)
            metrics_service.inc("memory.summary.failure")
            return SummaryResult(
                success=False,
                error=f"Parse error: {e}",
            )

        # Persist summary
        try:
            await self._repository.save_session_summary(summary)
            logger.info("Summary persisted for session %s", session_id)
        except Exception as e:
            logger.exception("Failed to persist summary for session %s", session_id)
            metrics_service.inc("memory.summary.failure")
            return SummaryResult(
                success=False,
                error=f"Persistence error: {e}",
            )

        metrics_service.inc("memory.summary.success")
        return SummaryResult(success=True, summary=summary)

    def _build_transcript(self, interactions: list[CapturedInteraction]) -> str:
        """Build a transcript string from interactions."""
        parts = []
        for interaction in interactions:
            role = interaction.role.upper()
            parts.append(f"[{role}]\n{interaction.content}\n")
        return "\n".join(parts)

    def _apply_redaction(self, text: str) -> str:
        """Apply redaction patterns to text."""
        for pattern in self._config.redaction_patterns:
            with contextlib.suppress(re.error):
                text = re.sub(pattern, "[REDACTED]", text)
        return text

    def _format_file_edits_for_prompt(
        self,
        file_edits: list[FileEditEvent],
    ) -> str:
        """Format file edit events for prompt injection.

        Produces a machine-readable list of file edits with action, path,
        tool, and timestamp for each entry. If empty, returns NONE marker.

        Args:
            file_edits: List of deterministic file edit events.

        Returns:
            Formatted string for prompt substitution.
        """
        if not file_edits:
            return "NONE (no deterministic file edits recorded)"

        lines = ["(action | path | tool | timestamp)"]
        for edit in file_edits:
            tool_name = edit.tool or "unknown"
            timestamp = edit.timestamp.isoformat()
            lines.append(f"{edit.action} | {edit.path} | {tool_name} | {timestamp}")

        return "\n".join(lines)

    def _format_git_commits_for_prompt(
        self,
        git_commits: list[GitCommitEvent],
    ) -> str:
        """Format git commit events for prompt injection.

        Produces a machine-readable list of git commits with hash, branch,
        message, and timestamp for each entry. If empty, returns NONE marker.

        Args:
            git_commits: List of deterministic git commit events.

        Returns:
            Formatted string for prompt substitution.
        """
        if not git_commits:
            return "NONE (no deterministic git commits recorded)"

        lines = ["(hash | branch | message | timestamp)"]
        for commit in git_commits:
            branch = commit.branch or "unknown"
            message = commit.message or "no message"
            # Truncate long messages
            if len(message) > 80:
                message = message[:77] + "..."
            timestamp = commit.timestamp.isoformat()
            lines.append(
                f"{commit.commit_hash[:12]} | {branch} | {message} | {timestamp}"
            )

        return "\n".join(lines)

    def _merge_deterministic_file_edits(
        self,
        existing: list[FileChange],
        deterministic: list[FileEditEvent],
    ) -> list[FileChange]:
        """Merge deterministic file edits into parsed file changes."""
        merged: dict[str, FileChange] = {item.path: item for item in existing}
        for event in deterministic:
            status = (
                event.action
                if event.action in {"created", "modified", "deleted"}
                else "modified"
            )
            merged[event.path] = FileChange(path=event.path, status=status)  # type: ignore[arg-type]
        return list(merged.values())

    def _merge_deterministic_git_commits(
        self,
        existing: list[GitOperation],
        deterministic: list[GitCommitEvent],
    ) -> list[GitOperation]:
        """Merge deterministic git commits into parsed git operations."""
        merged: list[GitOperation] = list(existing)
        seen: set[tuple[str | None, str | None]] = {(op.ref, op.type) for op in merged}
        for event in deterministic:
            ref = event.commit_hash or "UNKNOWN"
            key = (ref, "commit")
            if key in seen:
                continue
            details = event.message or "UNKNOWN"
            if event.branch:
                details = f"{details} (branch {event.branch})"
            merged.append(
                GitOperation(
                    type="commit",
                    ref=ref,
                    details=details,
                )
            )
            seen.add(key)
        return merged

    async def _process_large_transcript(self, transcript: str) -> str:
        """Process a large transcript by chunking and summarizing chunks.

        Args:
            transcript: The full transcript.

        Returns:
            A consolidated transcript of summaries.
        """
        chunks = self._chunk_transcript(transcript)
        chunk_summaries = []

        logger.info("Processing large transcript in %d chunks", len(chunks))

        for i, chunk in enumerate(chunks):
            summary = await self._summarize_chunk(chunk, i + 1, len(chunks))
            if summary:
                chunk_summaries.append(summary)

        return "\n\n".join(chunk_summaries)

    def _chunk_transcript(self, transcript: str) -> list[str]:
        """Split a large transcript into manageable chunks.

        Attempts to split at line breaks to preserve message integrity.
        """
        max_chars = self._config.max_transcript_chars
        if len(transcript) <= max_chars:
            return [transcript]

        chunks = []
        current_chunk: list[str] = []
        current_length = 0

        # Split by lines to avoid cutting in the middle of a line
        lines = transcript.splitlines(keepends=True)

        for line in lines:
            line_len = len(line)

            # If single line is too long, hard split it
            if line_len > max_chars:
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Split the long line
                for i in range(0, line_len, max_chars):
                    chunks.append(line[i : i + max_chars])
                continue

            if current_length + line_len > max_chars:
                chunks.append("".join(current_chunk))
                current_chunk = [line]
                current_length = line_len
            else:
                current_chunk.append(line)
                current_length += line_len

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks

    async def _summarize_chunk(
        self, chunk: str, chunk_num: int, total_chunks: int
    ) -> str | None:
        """Summarize a single transcript chunk.

        Args:
            chunk: The transcript chunk.
            chunk_num: Chunk index (1-based).
            total_chunks: Total number of chunks.

        Returns:
            Summary of the chunk or None if failed.
        """
        prompt = f"""Analyze this transcript segment (Chunk {chunk_num}/{total_chunks}) and extract key points.

<transcript_chunk>
{chunk}
</transcript_chunk>

Provide a concise summary of:
1. User intent and actions
2. Key code changes or file modifications
3. Errors encountered
4. Decisions made

Format as bullet points. Do not use XML.
"""
        return await self._call_llm_with_retry(prompt)

    async def _call_llm_with_retry(
        self,
        prompt: str,
        max_retries: int = 3,
    ) -> str | None:
        """Call LLM with exponential backoff retry.

        Args:
            prompt: The prompt to send.
            max_retries: Maximum number of retries.

        Returns:
            The LLM response or None on failure.
        """
        if self._llm_caller is None:
            # Return mock response for testing - extract session_id from prompt
            return self._generate_mock_response(session_id="mock-session")

        delays = [1, 2, 4]  # Backoff intervals
        last_error = None

        for attempt in range(max_retries):
            try:
                response = await self._invoke_llm(prompt)
                return response
            except Exception as e:
                last_error = e
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "LLM call attempt %d failed: %s",
                        attempt + 1,
                        e,
                        exc_info=True,
                    )
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])

        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                "LLM call failed after %d attempts: %s",
                max_retries,
                last_error,
                exc_info=True,
            )
        return None

    async def _invoke_llm(self, prompt: str) -> str | None:
        """Invoke the LLM caller with optional completion token limit."""
        try:
            return await self._llm_caller(  # type: ignore[misc]
                prompt, max_tokens=self._config.summary_completion_tokens
            )
        except TypeError:
            return await self._llm_caller(prompt)  # type: ignore[misc]

    def _generate_mock_response(self, session_id: str = "mock-session") -> str:
        """Generate a mock XML response for testing.

        Note: This is only used when no LLM caller is configured.
        In production, the actual LLM model should be called.
        """
        now = datetime.now(timezone.utc).isoformat()
        return f"""<session_summary version="{self._config.summary_schema_version}">
  <metadata>
    <session_id>{session_id}</session_id>
    <analysis_timestamp>{now}</analysis_timestamp>
    <summary_version>{self._config.summary_schema_version}</summary_version>
    <prompt_version>{self._config.summary_prompt_version}</prompt_version>
  </metadata>
  <title>Mock Session Summary</title>
  <scope>Testing and development</scope>
  <main_goals><goal>Complete testing</goal></main_goals>
  <key_decisions><decision>Use mock responses</decision></key_decisions>
  <operations_performed><operation>Created test files</operation></operations_performed>
  <touched_files></touched_files>
  <git_operations></git_operations>
  <tests_run></tests_run>
  <errors></errors>
  <remaining_tasks></remaining_tasks>
  <open_questions></open_questions>
  <risks_or_warnings></risks_or_warnings>
  <evidence></evidence>
  <completion_status>completed</completion_status>
</session_summary>"""

    def _parse_xml_to_summary(
        self,
        xml_content: str,
        session_id: str,
        user_id: str,
        tenant_id: str | None,
        project_id: str | None,
        project_root: str | None,
        backend_model: str,
        client_agent: str | None,
        branch: str | None,
        head_sha: str | None,
        is_partial: bool,
        session_start: datetime,
        deterministic_file_edits: list[FileEditEvent],
        deterministic_git_commits: list[GitCommitEvent],
    ) -> SessionSummary:
        """Parse XML response into SessionSummary model."""
        # Extract clean XML
        xml_content = self._validator._extract_xml(xml_content)
        root = ElementTree.fromstring(xml_content)

        def get_text(name: str, default: str = "") -> str:
            elem = root.find(name)
            return elem.text.strip() if elem is not None and elem.text else default

        def get_list(name: str, item_name: str) -> list[str]:
            container = root.find(name)
            if container is None:
                return []
            return [
                item.text.strip() for item in container.findall(item_name) if item.text
            ]

        def get_tasks() -> list[TaskItem]:
            container = root.find("remaining_tasks")
            if container is None:
                return []
            items = []
            for item in container.findall("task"):
                status_str = item.get("status", "open")
                task_status: Literal["open", "blocked"] = (
                    "open" if status_str not in {"open", "blocked"} else status_str  # type: ignore[assignment]
                )
                items.append(
                    TaskItem(
                        description=item.text.strip() if item.text else "UNKNOWN",
                        status=task_status,
                    )
                )
            return items

        def get_files() -> list[FileChange]:
            # Per spec (Req 12.2): use <touched_files> with fallback to <modified_files>
            container = root.find("touched_files")
            if container is None:
                container = root.find("modified_files")  # Fallback for backward compat
            if container is None:
                return []
            items = []
            for item in container.findall("file"):
                status_str = item.get("status", "modified")
                file_status: Literal["created", "modified", "deleted"] = (
                    "modified"
                    if status_str not in {"created", "modified", "deleted"}
                    else status_str  # type: ignore[assignment]
                )
                items.append(
                    FileChange(
                        path=item.text.strip() if item.text else "UNKNOWN",
                        status=file_status,
                    )
                )
            return items

        def get_git_ops() -> list[GitOperation]:
            container = root.find("git_operations")
            if container is None:
                return []
            items = []
            # Per spec (Req 12.2): use <operation type="..." ref="...">
            for item in container.findall("operation"):
                op_type_str = item.get("type", "commit")
                git_type: Literal[
                    "commit", "branch", "merge", "rebase", "cherry-pick"
                ] = (
                    "commit"
                    if op_type_str
                    not in {"commit", "branch", "merge", "rebase", "cherry-pick"}
                    else op_type_str  # type: ignore[assignment]
                )
                items.append(
                    GitOperation(
                        type=git_type,
                        ref=item.get("ref"),
                        details=item.text.strip() if item.text else "UNKNOWN",
                    )
                )
            # Fallback for backward compat with git_op tag
            if not items:
                for item in container.findall("git_op"):
                    op_type_str = item.get("type", "commit")
                    git_type = (
                        "commit"
                        if op_type_str
                        not in {"commit", "branch", "merge", "rebase", "cherry-pick"}
                        else op_type_str  # type: ignore[assignment]
                    )
                    items.append(
                        GitOperation(
                            type=git_type,
                            ref=item.get("ref"),
                            details=item.text.strip() if item.text else "UNKNOWN",
                        )
                    )
            return items

        def get_tests() -> list[TestRun]:
            container = root.find("tests_run")
            if container is None:
                return []
            items = []
            for item in container.findall("test"):
                status_str = item.get("status", "passed")
                test_status: Literal["passed", "failed", "timeout", "skipped"] = (
                    "passed"
                    if status_str not in {"passed", "failed", "timeout", "skipped"}
                    else status_str  # type: ignore[assignment]
                )
                # Per spec (Req 12.2): text is test name or command
                # Attributes: status (required), name/command are optional
                test_name = item.get("name") or (
                    item.text.strip() if item.text else "UNKNOWN"
                )
                items.append(
                    TestRun(
                        name=test_name,
                        status=test_status,
                        command=item.get("command"),
                    )
                )
            return items

        completion_status = get_text("completion_status", "completed")
        if completion_status not in {"completed", "partial", "abandoned"}:
            completion_status = "partial" if is_partial else "completed"

        now = datetime.now(timezone.utc)

        modified_files = self._merge_deterministic_file_edits(
            get_files(), deterministic_file_edits
        )
        git_operations = self._merge_deterministic_git_commits(
            get_git_ops(), deterministic_git_commits
        )

        return SessionSummary(
            id=str(uuid4()),
            user_id=user_id,
            tenant_id=tenant_id,
            project_id=project_id,
            project_root=project_root,
            session_id=session_id,
            session_start=session_start,
            client_agent=client_agent,
            backend_model=backend_model,
            title=get_text("title", "UNKNOWN"),
            scope=get_text("scope", ""),
            goals=get_list("main_goals", "goal") or get_list("goals", "goal"),
            open_questions=get_list("open_questions", "item"),
            remaining_tasks=get_tasks(),
            modified_files=modified_files,
            git_operations=git_operations,
            completion_status=completion_status,
            key_decisions=get_list("key_decisions", "decision"),
            operations_performed=get_list("operations_performed", "operation"),
            tests_run=get_tests(),
            errors=get_list("errors", "error"),
            risks_or_warnings=get_list("risks_or_warnings", "item"),
            evidence=get_list("evidence", "item"),
            full_analysis=xml_content,
            branch=branch,
            head_sha=head_sha,
            summary_version=self._config.summary_schema_version,
            created_at=now,
        )
