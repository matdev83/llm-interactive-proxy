"""Property-based tests for deterministic tool events in summaries.

Feature: proxy-mem
Property: 22
Validates: Requirements 9.13 - Deterministic tool events reflected in summaries
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast

from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import FileEditEvent, GitCommitEvent
from src.core.memory.repository import IMemoryRepository
from src.core.memory.summary_generator import SummaryGenerator
from tests.utils.hypothesis_config import property_test_settings


class _StubRepository:
    async def initialize_schema(self) -> None:
        return None

    async def save_session_summary(self, summary: object) -> None:
        return None

    async def get_recent_sessions(
        self, *args: object, **kwargs: object
    ) -> list[object]:
        return []

    async def delete_old_sessions(self, *args: object, **kwargs: object) -> int:
        return 0

    async def get_or_create_project_id(self, *args: object, **kwargs: object) -> str:
        return "proj-1"


@given(
    file_path=st.text(min_size=1, max_size=50),
    action=st.sampled_from(["created", "modified", "deleted", "unknown"]),
    commit_hash=st.text(min_size=7, max_size=12, alphabet="0123456789abcdef"),
)
@property_test_settings(suppress_health_check=[HealthCheck.filter_too_much])
def test_property_22_deterministic_events_merge_into_summary(
    file_path: str,
    action: str,
    commit_hash: str,
) -> None:
    """Deterministic tool events should appear in parsed summaries."""
    config = MemoryConfiguration()
    generator = SummaryGenerator(
        config=config,
        repository=cast(IMemoryRepository, _StubRepository()),
    )

    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    action_literal = cast(Literal["created", "modified", "deleted", "unknown"], action)
    file_edits = [
        FileEditEvent(
            path=file_path,
            action=action_literal,
            tool="apply_patch",
            timestamp=now,
        )
    ]
    git_commits = [
        GitCommitEvent(
            commit_hash=commit_hash, message="msg", branch="main", timestamp=now
        )
    ]

    xml = """<session_summary version="v1">
  <metadata>
    <session_id>sess-1</session_id>
    <analysis_timestamp>2024-01-01T00:00:00Z</analysis_timestamp>
    <summary_version>v1</summary_version>
  </metadata>
  <title>Test</title>
  <completion_status>completed</completion_status>
</session_summary>"""

    summary = generator._parse_xml_to_summary(
        xml_content=xml,
        session_id="sess-1",
        user_id="user-1",
        tenant_id=None,
        project_id=None,
        project_root=None,
        backend_model="backend:model",
        client_agent=None,
        branch=None,
        head_sha=None,
        is_partial=False,
        session_start=now,
        deterministic_file_edits=file_edits,
        deterministic_git_commits=git_commits,
    )

    file_paths = {item.path for item in summary.modified_files}
    assert file_path in file_paths

    commit_refs = {item.ref for item in summary.git_operations if item.type == "commit"}
    assert commit_hash in commit_refs
