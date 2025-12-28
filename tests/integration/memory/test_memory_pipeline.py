"""Integration tests for ProxyMem pipeline."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from src.core.memory.analysis_worker import AnalysisWorker
from src.core.memory.config import MemoryConfiguration
from src.core.memory.context_injector import ContextInjector
from src.core.memory.models import CapturedInteraction, FileEditEvent, GitCommitEvent
from src.core.memory.service import MemoryService
from src.core.memory.sqlite_repository import MemoryRepository
from src.core.memory.summary_generator import SummaryGenerator


def _create_interaction(content: str, role: str) -> CapturedInteraction:
    return CapturedInteraction(
        role=role,
        content=content,
        timestamp=datetime.now(timezone.utc),
    )


def _summary_xml(title: str) -> str:
    return f"""<session_summary version="v1">
  <metadata>
    <session_id>sess</session_id>
    <analysis_timestamp>2024-01-01T00:00:00Z</analysis_timestamp>
    <summary_version>v1</summary_version>
  </metadata>
  <title>{title}</title>
  <completion_status>completed</completion_status>
</session_summary>"""


@pytest.mark.asyncio
async def test_memory_end_to_end_pipeline() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.sqlite3")
        config = MemoryConfiguration(
            available=True,
            database_path=db_path,
            summarization_delay_seconds=0,
            require_project_discovery=False,
            context_relevance_threshold=0.0,
        )
        repo = MemoryRepository(config)
        memory_service = MemoryService(config=config, repository=repo)

        async def llm_caller(prompt: str, *, max_tokens: int | None = None) -> str:
            return _summary_xml("End-to-End Session")

        generator = SummaryGenerator(
            config=config, repository=repo, llm_caller=llm_caller
        )
        worker = AnalysisWorker(
            memory_service=memory_service,
            summary_generator=generator,
            config=config,
        )

        await memory_service.enable_for_session(
            "sess-1", "user-1", project_root="/proj"
        )
        await memory_service.capture_interaction(
            "sess-1", _create_interaction("Hello", "user")
        )
        await memory_service.capture_interaction(
            "sess-1", _create_interaction("Hi", "assistant")
        )
        await memory_service.mark_session_complete("sess-1")

        session_id = await memory_service.get_pending_analysis_session()
        assert session_id == "sess-1"
        await worker._process_session(session_id)

        summaries = await repo.get_recent_sessions("user-1", limit=5)
        assert len(summaries) == 1
        assert summaries[0].title == "End-to-End Session"

        injector = ContextInjector(config=config, repository=repo)
        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Work on the same project",
            project_root="/proj",
        )
        assert context is not None

        await repo.close()


@pytest.mark.asyncio
async def test_memory_pipeline_deterministic_tool_events() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.sqlite3")
        config = MemoryConfiguration(
            available=True,
            database_path=db_path,
            summarization_delay_seconds=0,
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        memory_service = MemoryService(config=config, repository=repo)

        async def llm_caller(prompt: str, *, max_tokens: int | None = None) -> str:
            return _summary_xml("Tool Events Session")

        generator = SummaryGenerator(
            config=config, repository=repo, llm_caller=llm_caller
        )
        worker = AnalysisWorker(
            memory_service=memory_service,
            summary_generator=generator,
            config=config,
        )

        await memory_service.enable_for_session(
            "sess-2", "user-1", project_root="/proj"
        )
        await memory_service.capture_interaction(
            "sess-2", _create_interaction("Edit file", "user")
        )

        now = datetime.now(timezone.utc)
        await memory_service.record_tool_event(
            "sess-2",
            FileEditEvent(
                path="src/app.py",
                action="modified",
                tool="apply_patch",
                timestamp=now,
            ),
        )
        await memory_service.record_tool_event(
            "sess-2",
            GitCommitEvent(
                commit_hash="abc123def456",
                message="Update app",
                branch="main",
                timestamp=now,
            ),
        )

        await memory_service.mark_session_complete("sess-2")
        session_id = await memory_service.get_pending_analysis_session()
        assert session_id == "sess-2"
        await worker._process_session(session_id)

        summaries = await repo.get_recent_sessions("user-1", limit=5)
        assert len(summaries) == 1
        summary = summaries[0]

        file_paths = {item.path for item in summary.modified_files}
        assert "src/app.py" in file_paths

        commit_refs = {
            item.ref for item in summary.git_operations if item.type == "commit"
        }
        assert "abc123def456" in commit_refs

        await repo.close()


@pytest.mark.asyncio
async def test_memory_context_project_scoping_and_threshold() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.sqlite3")
        config = MemoryConfiguration(
            available=True,
            database_path=db_path,
            summarization_delay_seconds=0,
            require_project_discovery=False,
            context_relevance_threshold=1.0,
        )
        repo = MemoryRepository(config)
        memory_service = MemoryService(config=config, repository=repo)

        async def llm_caller(prompt: str, *, max_tokens: int | None = None) -> str:
            if "Project A" in prompt:
                return _summary_xml("Project A Session")
            return _summary_xml("Project B Session")

        generator = SummaryGenerator(
            config=config, repository=repo, llm_caller=llm_caller
        )
        worker = AnalysisWorker(
            memory_service=memory_service,
            summary_generator=generator,
            config=config,
        )

        await memory_service.enable_for_session(
            "sess-a", "user-1", project_root="/proj-a"
        )
        await memory_service.capture_interaction(
            "sess-a", _create_interaction("Project A work", "user")
        )
        await memory_service.mark_session_complete("sess-a")

        await memory_service.enable_for_session(
            "sess-b", "user-1", project_root="/proj-b"
        )
        await memory_service.capture_interaction(
            "sess-b", _create_interaction("Project B work", "user")
        )
        await memory_service.mark_session_complete("sess-b")

        session_id = await memory_service.get_pending_analysis_session()
        assert session_id is not None
        await worker._process_session(session_id)
        session_id = await memory_service.get_pending_analysis_session()
        assert session_id is not None
        await worker._process_session(session_id)

        injector = ContextInjector(config=config, repository=repo)
        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Unrelated request",
            project_root="/proj-a",
        )
        assert context is None

        await repo.close()


@pytest.mark.asyncio
async def test_memory_context_project_scoping() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.sqlite3")
        config = MemoryConfiguration(
            available=True,
            database_path=db_path,
            summarization_delay_seconds=0,
            require_project_discovery=False,
            context_relevance_threshold=0.0,
        )
        repo = MemoryRepository(config)
        memory_service = MemoryService(config=config, repository=repo)

        async def llm_caller(prompt: str, *, max_tokens: int | None = None) -> str:
            if "Project A" in prompt:
                return _summary_xml("Project A Session")
            return _summary_xml("Project B Session")

        generator = SummaryGenerator(
            config=config, repository=repo, llm_caller=llm_caller
        )
        worker = AnalysisWorker(
            memory_service=memory_service,
            summary_generator=generator,
            config=config,
        )

        await memory_service.enable_for_session(
            "sess-a2", "user-1", project_root="/proj-a"
        )
        await memory_service.capture_interaction(
            "sess-a2", _create_interaction("Project A work", "user")
        )
        await memory_service.mark_session_complete("sess-a2")

        await memory_service.enable_for_session(
            "sess-b2", "user-1", project_root="/proj-b"
        )
        await memory_service.capture_interaction(
            "sess-b2", _create_interaction("Project B work", "user")
        )
        await memory_service.mark_session_complete("sess-b2")

        session_id = await memory_service.get_pending_analysis_session()
        assert session_id is not None
        await worker._process_session(session_id)
        session_id = await memory_service.get_pending_analysis_session()
        assert session_id is not None
        await worker._process_session(session_id)

        injector = ContextInjector(config=config, repository=repo)
        context = await injector.get_context_for_session(
            user_id="user-1",
            current_prompt="Project A follow-up",
            project_root="/proj-a",
        )

        assert context is not None
        assert "Project A Session" in context
        assert "Project B Session" not in context

        await repo.close()


@pytest.mark.asyncio
async def test_memory_chunked_summary_generation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "memory.sqlite3")
        config = MemoryConfiguration(
            available=True,
            database_path=db_path,
            summarization_delay_seconds=0,
            require_project_discovery=False,
            max_transcript_chars=50,
        )
        repo = MemoryRepository(config)
        memory_service = MemoryService(config=config, repository=repo)

        async def llm_caller(prompt: str, *, max_tokens: int | None = None) -> str:
            if "<transcript_chunk>" in prompt:
                return "chunk summary"
            return _summary_xml("Chunked Session")

        generator = SummaryGenerator(
            config=config, repository=repo, llm_caller=llm_caller
        )
        worker = AnalysisWorker(
            memory_service=memory_service,
            summary_generator=generator,
            config=config,
        )

        await memory_service.enable_for_session(
            "sess-chunk", "user-1", project_root="/proj"
        )
        await memory_service.capture_interaction(
            "sess-chunk", _create_interaction("A" * 80, "user")
        )
        await memory_service.mark_session_complete("sess-chunk")

        session_id = await memory_service.get_pending_analysis_session()
        assert session_id is not None
        await worker._process_session(session_id)

        summaries = await repo.get_recent_sessions("user-1", limit=5)
        assert len(summaries) == 1
        assert summaries[0].title == "Chunked Session"

        await repo.close()
