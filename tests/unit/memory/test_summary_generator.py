"""Unit tests for SummaryGenerator and SummaryValidator."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import CapturedInteraction
from src.core.memory.sqlite_repository import MemoryRepository
from src.core.memory.summary_generator import (
    SummaryGenerator,
    SummaryValidator,
)


def create_interaction(
    content: str = "Test content",
    role: str = "user",
) -> CapturedInteraction:
    """Create a test CapturedInteraction."""
    return CapturedInteraction(
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


class TestSummaryValidator:
    """Tests for SummaryValidator."""

    def test_validates_correct_xml(self) -> None:
        """Test validation passes for correct XML."""
        validator = SummaryValidator()
        xml = """<session_summary version="v1">
            <title>Test Summary</title>
            <completion_status>completed</completion_status>
        </session_summary>"""

        is_valid, error = validator.validate(xml)
        assert is_valid is True
        assert error is None

    def test_rejects_missing_title(self) -> None:
        """Test validation fails for missing title."""
        validator = SummaryValidator()
        xml = """<session_summary version="v1">
            <completion_status>completed</completion_status>
        </session_summary>"""

        is_valid, error = validator.validate(xml)
        assert is_valid is False
        assert "title" in error.lower()

    def test_rejects_missing_completion_status(self) -> None:
        """Test validation fails for missing completion_status."""
        validator = SummaryValidator()
        xml = """<session_summary version="v1">
            <title>Test</title>
        </session_summary>"""

        is_valid, error = validator.validate(xml)
        assert is_valid is False
        assert "completion_status" in error.lower()

    def test_rejects_invalid_completion_status(self) -> None:
        """Test validation fails for invalid completion_status value."""
        validator = SummaryValidator()
        xml = """<session_summary version="v1">
            <title>Test</title>
            <completion_status>invalid</completion_status>
        </session_summary>"""

        is_valid, error = validator.validate(xml)
        assert is_valid is False
        assert "invalid" in error.lower()

    def test_rejects_wrong_root_element(self) -> None:
        """Test validation fails for wrong root element."""
        validator = SummaryValidator()
        xml = """<summary>
            <title>Test</title>
        </summary>"""

        is_valid, error = validator.validate(xml)
        assert is_valid is False
        assert "session_summary" in error.lower()

    def test_rejects_invalid_xml(self) -> None:
        """Test validation fails for malformed XML."""
        validator = SummaryValidator()
        xml = "<session_summary><unclosed>"

        is_valid, error = validator.validate(xml)
        assert is_valid is False
        assert "parse" in error.lower()

    def test_extracts_xml_with_preamble(self) -> None:
        """Test XML extraction strips preamble text."""
        validator = SummaryValidator()
        content = """Here is my summary:

<session_summary version="v1">
    <title>Test</title>
    <completion_status>completed</completion_status>
</session_summary>

That's all!"""

        is_valid, error = validator.validate(content)
        assert is_valid is True

    def test_rejects_no_xml(self) -> None:
        """Test validation fails when no XML present."""
        validator = SummaryValidator()
        content = "This is just plain text without any XML."

        is_valid, error = validator.validate(content)
        assert is_valid is False
        assert "no valid xml" in error.lower()


class TestSummaryGenerator:
    """Tests for SummaryGenerator."""

    @pytest.fixture
    def temp_db_path(self) -> Path:
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_memory.sqlite3"

    @pytest.fixture
    def config(self, temp_db_path: Path) -> MemoryConfiguration:
        """Create test configuration."""
        return MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            require_project_discovery=False,
        )

    @pytest.fixture
    def repository(self, config: MemoryConfiguration) -> MemoryRepository:
        """Create repository instance."""
        return MemoryRepository(config)

    @pytest.fixture
    def generator(
        self, config: MemoryConfiguration, repository: MemoryRepository
    ) -> SummaryGenerator:
        """Create generator instance."""
        return SummaryGenerator(config, repository)

    @pytest.mark.asyncio
    async def test_generates_summary_with_mock(
        self, generator: SummaryGenerator
    ) -> None:
        """Test summary generation with mock LLM response."""
        interactions = [
            create_interaction("Hello, help me with a task", "user"),
            create_interaction("Sure, I can help with that", "assistant"),
        ]

        result = await generator.generate_summary(
            session_id="sess-1",
            user_id="user-1",
            interactions=interactions,
            backend_model="openai:gpt-4o",
        )

        assert result.success is True
        assert result.summary is not None
        assert result.summary.session_id == "sess-1"
        assert result.summary.user_id == "user-1"

    @pytest.mark.asyncio
    async def test_fails_with_empty_interactions(
        self, generator: SummaryGenerator
    ) -> None:
        """Test summary generation fails with no interactions."""
        result = await generator.generate_summary(
            session_id="sess-1",
            user_id="user-1",
            interactions=[],
        )

        assert result.success is False
        assert "no interactions" in result.error.lower()

    @pytest.mark.asyncio
    async def test_builds_transcript(self, generator: SummaryGenerator) -> None:
        """Test transcript building from interactions."""
        interactions = [
            create_interaction("User message", "user"),
            create_interaction("Assistant response", "assistant"),
        ]

        transcript = generator._build_transcript(interactions)

        assert "[USER]" in transcript
        assert "[ASSISTANT]" in transcript
        assert "User message" in transcript
        assert "Assistant response" in transcript

    @pytest.mark.asyncio
    async def test_applies_redaction(self, temp_db_path: Path) -> None:
        """Test redaction pattern application."""
        config = MemoryConfiguration(
            available=True,
            database_path=str(temp_db_path),
            redaction_patterns=[r"secret-\w+"],
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        generator = SummaryGenerator(config, repo)

        text = "Here is secret-abc123 and secret-xyz789"
        result = generator._apply_redaction(text)

        assert "secret-abc123" not in result
        assert "secret-xyz789" not in result
        assert "[REDACTED]" in result

    @pytest.mark.asyncio
    async def test_chunks_large_transcript(self, generator: SummaryGenerator) -> None:
        """Test transcript chunking for large content."""
        large_transcript = "A" * 100000  # 100KB

        result = generator._chunk_transcript(large_transcript)

        assert len(result) <= generator._config.max_transcript_chars + 100
        assert "TRUNCATED" in result

    @pytest.mark.asyncio
    async def test_persists_summary(
        self,
        generator: SummaryGenerator,
        repository: MemoryRepository,
    ) -> None:
        """Test that generated summaries are persisted."""
        await repository.initialize_schema()

        interactions = [
            create_interaction("Hello", "user"),
            create_interaction("Hi there", "assistant"),
        ]

        result = await generator.generate_summary(
            session_id="sess-1",
            user_id="user-1",
            interactions=interactions,
            backend_model="openai:gpt-4o",
        )

        assert result.success is True

        # Verify persisted
        summaries = await repository.get_recent_sessions("user-1", limit=10)
        assert len(summaries) == 1
        assert summaries[0].session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_parses_all_fields(self, generator: SummaryGenerator) -> None:
        """Test XML parsing extracts all fields correctly."""
        xml = """<session_summary version="v1">
            <title>Test Summary</title>
            <scope>Testing scope</scope>
            <goals><goal>Goal 1</goal><goal>Goal 2</goal></goals>
            <key_decisions><decision>Decision 1</decision></key_decisions>
            <operations_performed><operation>Op 1</operation></operations_performed>
            <modified_files>
                <file status="created">src/new.py</file>
                <file status="modified">src/old.py</file>
            </modified_files>
            <git_operations>
                <git_op type="commit" ref="abc123">Initial commit</git_op>
            </git_operations>
            <tests_run>
                <test name="test_example" status="passed" command="pytest"/>
            </tests_run>
            <errors><error>Error 1</error></errors>
            <remaining_tasks>
                <task status="open">Task 1</task>
                <task status="blocked">Task 2</task>
            </remaining_tasks>
            <open_questions><question>Question 1</question></open_questions>
            <risks_or_warnings><warning>Warning 1</warning></risks_or_warnings>
            <evidence><item>Evidence 1</item></evidence>
            <completion_status>completed</completion_status>
        </session_summary>"""

        summary = generator._parse_xml_to_summary(
            xml,
            session_id="sess-1",
            user_id="user-1",
            tenant_id=None,
            project_id="proj-1",
            project_root="/home/user",
            backend_model="openai:gpt-4o",
            client_agent="test-client",
            branch="main",
            head_sha="abc123",
            is_partial=False,
            session_start=datetime.now(timezone.utc),
        )

        assert summary.title == "Test Summary"
        assert summary.scope == "Testing scope"
        assert len(summary.goals) == 2
        assert len(summary.key_decisions) == 1
        assert len(summary.operations_performed) == 1
        assert len(summary.modified_files) == 2
        assert summary.modified_files[0].status == "created"
        assert len(summary.git_operations) == 1
        assert summary.git_operations[0].type == "commit"
        assert len(summary.tests_run) == 1
        assert summary.tests_run[0].status == "passed"
        assert len(summary.errors) == 1
        assert len(summary.remaining_tasks) == 2
        assert summary.remaining_tasks[1].status == "blocked"
        assert len(summary.open_questions) == 1
        assert len(summary.risks_or_warnings) == 1
        assert len(summary.evidence) == 1
        assert summary.completion_status == "completed"
        assert summary.branch == "main"
        assert summary.head_sha == "abc123"
