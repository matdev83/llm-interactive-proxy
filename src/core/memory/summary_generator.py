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
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import (
    CapturedInteraction,
    FileChange,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)
from src.core.memory.prompt_loader import PromptLoader

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


class SummaryValidator:
    """Validates XML summaries against schema requirements."""

    VALID_COMPLETION_STATUSES = {"completed", "partial", "abandoned"}
    VALID_TASK_STATUSES = {"open", "blocked"}
    VALID_FILE_STATUSES = {"created", "modified", "deleted"}
    VALID_GIT_TYPES = {"commit", "branch", "merge", "rebase", "cherry-pick"}
    VALID_TEST_STATUSES = {"passed", "failed", "timeout", "skipped"}

    def validate(self, xml_content: str) -> tuple[bool, str | None]:
        """Validate XML content against summary schema.

        Args:
            xml_content: The XML string to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        # Strip any preamble/postamble
        xml_content = self._extract_xml(xml_content)

        if not xml_content:
            return False, "No valid XML found in response"

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as e:
            return False, f"XML parse error: {e}"

        if root.tag != "session_summary":
            return False, f"Expected root element 'session_summary', got '{root.tag}'"

        # Check required elements
        required = ["title", "completion_status"]
        for elem_name in required:
            elem = root.find(elem_name)
            if elem is None or not elem.text:
                return False, f"Missing required element: {elem_name}"

        # Validate completion_status
        status_elem = root.find("completion_status")
        if (
            status_elem is not None
            and status_elem.text
            and status_elem.text not in self.VALID_COMPLETION_STATUSES
        ):
            return False, f"Invalid completion_status: {status_elem.text}"

        return True, None

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
        llm_caller: Any = None,
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

        Returns:
            SummaryResult with success status and summary or error.
        """
        if not interactions:
            return SummaryResult(
                success=False,
                error="No interactions to summarize",
            )

        # Build transcript
        transcript = self._build_transcript(interactions)

        # Apply redaction
        transcript = self._apply_redaction(transcript)

        # Chunk if needed
        if len(transcript) > self._config.max_transcript_chars:
            transcript = self._chunk_transcript(transcript)

        # Build prompt
        prompt_template = self._prompt_loader.load_summary_prompt()
        now = datetime.now(timezone.utc)

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
        }

        prompt = self._prompt_loader.substitute_variables(prompt_template, variables)

        # Call LLM with retry
        xml_response = await self._call_llm_with_retry(prompt)
        if xml_response is None:
            return SummaryResult(
                success=False,
                error="LLM call failed after retries",
            )

        # Validate response
        is_valid, error = self._validator.validate(xml_response)
        if not is_valid:
            logger.warning(
                "Summary validation failed for session %s: %s",
                session_id,
                error,
            )
            return SummaryResult(
                success=False,
                error=f"Validation failed: {error}",
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
            )
        except Exception as e:
            logger.exception("Failed to parse summary XML for session %s", session_id)
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
            return SummaryResult(
                success=False,
                error=f"Persistence error: {e}",
            )

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

    def _chunk_transcript(self, transcript: str) -> str:
        """Chunk a large transcript to fit within limits."""
        max_chars = self._config.max_transcript_chars

        if len(transcript) <= max_chars:
            return transcript

        # Take first and last portions
        half = max_chars // 2
        return (
            transcript[:half]
            + "\n\n[... TRANSCRIPT TRUNCATED ...]\n\n"
            + transcript[-half:]
        )

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
            # Return mock response for testing
            return self._generate_mock_response()

        delays = [1, 2, 4]  # Backoff intervals
        last_error = None

        for attempt in range(max_retries):
            try:
                response: str = await self._llm_caller(prompt)
                return response
            except Exception as e:
                last_error = e
                logger.warning(
                    "LLM call attempt %d failed: %s",
                    attempt + 1,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])

        logger.error("LLM call failed after %d attempts: %s", max_retries, last_error)
        return None

    def _generate_mock_response(self) -> str:
        """Generate a mock XML response for testing."""
        return """<session_summary version="v1">
  <title>Mock Session Summary</title>
  <scope>Testing and development</scope>
  <goals><goal>Complete testing</goal></goals>
  <key_decisions><decision>Use mock responses</decision></key_decisions>
  <operations_performed><operation>Created test files</operation></operations_performed>
  <modified_files></modified_files>
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
            container = root.find("modified_files")
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
            for item in container.findall("git_op"):
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
                items.append(
                    TestRun(
                        name=item.get("name", "UNKNOWN"),
                        status=test_status,
                        command=item.get("command"),
                    )
                )
            return items

        completion_status = get_text("completion_status", "completed")
        if completion_status not in {"completed", "partial", "abandoned"}:
            completion_status = "partial" if is_partial else "completed"

        now = datetime.now(timezone.utc)

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
            goals=get_list("goals", "goal"),
            open_questions=get_list("open_questions", "question"),
            remaining_tasks=get_tasks(),
            modified_files=get_files(),
            git_operations=get_git_ops(),
            completion_status=completion_status,
            key_decisions=get_list("key_decisions", "decision"),
            operations_performed=get_list("operations_performed", "operation"),
            tests_run=get_tests(),
            errors=get_list("errors", "error"),
            risks_or_warnings=get_list("risks_or_warnings", "warning"),
            evidence=get_list("evidence", "item"),
            full_analysis=xml_content,
            branch=branch,
            head_sha=head_sha,
            summary_version=self._config.summary_schema_version,
            created_at=now,
        )
