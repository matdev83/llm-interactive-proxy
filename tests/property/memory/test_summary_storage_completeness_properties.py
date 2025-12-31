"""Property-based tests for summary storage completeness.

Feature: proxy-mem
Property: 7
Validates: Requirements 7.2, 12.2, 12.7 - Summary storage completeness
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from freezegun import freeze_time
from hypothesis import HealthCheck, given
from hypothesis import strategies as st
from pydantic import ValidationError
from src.core.memory.models import (
    FileChange,
    GitOperation,
    SessionSummary,
    TaskItem,
    TestRun,
)
from tests.utils.hypothesis_config import property_test_settings


@st.composite
def task_item_strategy(draw: st.DrawFn) -> TaskItem:
    """Generate a TaskItem."""
    return TaskItem(
        description=draw(st.text(min_size=1, max_size=100)),
        status=draw(st.sampled_from(["open", "blocked"])),
    )


@st.composite
def file_change_strategy(draw: st.DrawFn) -> FileChange:
    """Generate a FileChange."""
    return FileChange(
        path=draw(st.text(min_size=1, max_size=100)),
        status=draw(st.sampled_from(["created", "modified", "deleted"])),
    )


@st.composite
def git_operation_strategy(draw: st.DrawFn) -> GitOperation:
    """Generate a GitOperation."""
    return GitOperation(
        type=draw(
            st.sampled_from(["commit", "branch", "merge", "rebase", "cherry-pick"])
        ),
        ref=draw(st.one_of(st.none(), st.text(min_size=1, max_size=40))),
        details=draw(st.text(min_size=1, max_size=200)),
    )


@st.composite
def _test_run_strategy(draw: st.DrawFn) -> TestRun:
    """Generate a TestRun."""
    return TestRun(
        name=draw(st.text(min_size=1, max_size=100)),
        status=draw(st.sampled_from(["passed", "failed", "timeout", "skipped"])),
        command=draw(st.one_of(st.none(), st.text(min_size=1, max_size=200))),
    )


@st.composite
def session_summary_strategy(draw: st.DrawFn) -> SessionSummary:
    """Generate a complete SessionSummary with all required fields."""
    # Use fixed time - tests should use @freeze_time decorator
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return SessionSummary(
        id=draw(st.text(min_size=8, max_size=36, alphabet="0123456789abcdef-")),
        user_id=draw(st.text(min_size=1, max_size=50)),
        tenant_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
        project_id=draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
        project_root=draw(st.one_of(st.none(), st.text(min_size=1, max_size=200))),
        session_id=draw(st.text(min_size=8, max_size=36)),
        session_start=now,
        client_agent=draw(st.one_of(st.none(), st.text(min_size=1, max_size=50))),
        backend_model=draw(
            st.text(min_size=3, max_size=50).map(lambda x: f"backend:{x}")
        ),
        title=draw(st.text(min_size=1, max_size=200)),
        scope=draw(st.text(min_size=1, max_size=500)),
        goals=draw(st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)),
        open_questions=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        remaining_tasks=draw(st.lists(task_item_strategy(), min_size=0, max_size=5)),
        modified_files=draw(st.lists(file_change_strategy(), min_size=0, max_size=10)),
        git_operations=draw(st.lists(git_operation_strategy(), min_size=0, max_size=5)),
        completion_status=draw(st.sampled_from(["completed", "partial", "abandoned"])),
        key_decisions=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        operations_performed=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        tests_run=draw(st.lists(_test_run_strategy(), min_size=0, max_size=10)),
        errors=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        risks_or_warnings=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        evidence=draw(
            st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=5)
        ),
        full_analysis=draw(st.text(min_size=10, max_size=500)),
        branch=draw(st.one_of(st.none(), st.text(min_size=1, max_size=100))),
        head_sha=draw(st.one_of(st.none(), st.text(min_size=7, max_size=40))),
        summary_version=draw(st.sampled_from(["v1", "v2"])),
        created_at=now,
    )


@st.composite
def minimal_session_summary_for_nested_validation(draw: st.DrawFn) -> SessionSummary:
    """Generate a minimal SessionSummary for nested model validation.

    This strategy is optimized for test_property_7_summary_nested_models_valid.
    It generates only the minimum required fields with small data sizes,
    focusing on the nested models that are being validated.
    """
    # Use fixed time - tests should use @freeze_time decorator
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return SessionSummary(
        id="test-id",
        user_id="test-user",
        tenant_id=None,
        project_id=None,
        project_root=None,
        session_id="test-session",
        session_start=now,
        client_agent=None,
        backend_model="backend:model",
        title="test",
        scope="test",
        goals=[],
        open_questions=[],
        remaining_tasks=draw(st.lists(task_item_strategy(), min_size=0, max_size=2)),
        modified_files=draw(st.lists(file_change_strategy(), min_size=0, max_size=2)),
        git_operations=draw(st.lists(git_operation_strategy(), min_size=0, max_size=2)),
        completion_status="completed",
        key_decisions=[],
        operations_performed=[],
        tests_run=draw(st.lists(_test_run_strategy(), min_size=0, max_size=2)),
        errors=[],
        risks_or_warnings=[],
        evidence=[],
        full_analysis="test analysis",
        branch=None,
        head_sha=None,
        summary_version="v1",
        created_at=now,
    )


@given(summary=session_summary_strategy())
@property_test_settings(
    max_examples=20,
    suppress_health_check=[
        HealthCheck.filter_too_much
    ],  # Reduced from 30 for performance
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_has_all_required_fields(summary: SessionSummary) -> None:
    """
    Property 7: Summary storage completeness.

    For any successfully generated summary, all required fields should be present.

    Validates: Requirements 7.2, 12.2
    """
    # Required fields must be present and non-None
    assert summary.id is not None
    assert summary.user_id is not None
    assert summary.session_id is not None
    assert summary.session_start is not None
    assert summary.backend_model is not None
    assert summary.title is not None
    assert summary.scope is not None
    assert summary.completion_status is not None
    assert summary.full_analysis is not None
    assert summary.summary_version is not None
    assert summary.created_at is not None

    # Collection fields should be lists (not None)
    assert isinstance(summary.goals, list)
    assert isinstance(summary.remaining_tasks, list)
    assert isinstance(summary.modified_files, list)
    assert isinstance(summary.git_operations, list)
    assert isinstance(summary.key_decisions, list)
    assert isinstance(summary.operations_performed, list)
    assert isinstance(summary.tests_run, list)
    assert isinstance(summary.errors, list)
    assert isinstance(summary.risks_or_warnings, list)
    assert isinstance(summary.evidence, list)
    assert isinstance(summary.open_questions, list)


@given(summary=session_summary_strategy())
@property_test_settings(
    max_examples=10,
    suppress_health_check=[
        HealthCheck.filter_too_much
    ],  # Reduced from 15 for performance
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_model_format(summary: SessionSummary) -> None:
    """
    Property 7: Summary model format validation.

    The backend_model field should be in backend:model format.

    Validates: Requirements 7.2
    """
    assert ":" in summary.backend_model
    backend, model = summary.backend_model.split(":", 1)
    assert len(backend) > 0
    assert len(model) > 0


@given(summary=session_summary_strategy())
@property_test_settings(
    max_examples=8,  # Reduced for performance
    suppress_health_check=[HealthCheck.filter_too_much],
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_completion_status_valid(summary: SessionSummary) -> None:
    """
    Property 7: Summary completion status validation.

    The completion_status field should be one of the valid values.

    Validates: Requirements 12.2
    """
    valid_statuses = {"completed", "partial", "abandoned"}
    assert summary.completion_status in valid_statuses


@given(summary=minimal_session_summary_for_nested_validation())
@property_test_settings(
    max_examples=5,
    suppress_health_check=[HealthCheck.filter_too_much],  # Reduced from 10 to 5
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_nested_models_valid(summary: SessionSummary) -> None:
    """
    Property 7: Summary nested model validation.

    All nested models (TaskItem, FileChange, GitOperation, TestRun) should have valid values.

    Validates: Requirements 12.2, 12.7
    """
    # Validate TaskItem entries
    for task in summary.remaining_tasks:
        assert task.description is not None
        assert task.status in {"open", "blocked"}

    # Validate FileChange entries
    for file_change in summary.modified_files:
        assert file_change.path is not None
        assert file_change.status in {"created", "modified", "deleted"}

    # Validate GitOperation entries
    for git_op in summary.git_operations:
        assert git_op.type in {"commit", "branch", "merge", "rebase", "cherry-pick"}
        assert git_op.details is not None

    # Validate TestRun entries
    for test_run in summary.tests_run:
        assert test_run.name is not None
        assert test_run.status in {"passed", "failed", "timeout", "skipped"}


@given(summary=session_summary_strategy())
@property_test_settings(
    max_examples=5, suppress_health_check=[HealthCheck.filter_too_much]
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_is_immutable(summary: SessionSummary) -> None:
    """
    Property 7: Summary immutability.

    SessionSummary should be frozen and immutable.

    Validates: Requirements 7.2
    """
    # Attempting to modify a frozen model should raise an error
    # Attempting to modify a frozen model should raise an error
    with pytest.raises(ValidationError):
        summary.title = "Modified title"  # type: ignore[misc]


@given(summary=session_summary_strategy())
@property_test_settings(
    max_examples=10, suppress_health_check=[HealthCheck.filter_too_much]
)
@freeze_time("2024-01-01 12:00:00")
def test_property_7_summary_serializable(summary: SessionSummary) -> None:
    """
    Property 7: Summary serialization.

    SessionSummary should be serializable to dict for database storage.

    Validates: Requirements 7.2, 12.7
    """
    # Should be able to serialize to dict
    summary_dict = summary.model_dump()
    assert isinstance(summary_dict, dict)

    # Should be able to serialize to JSON
    summary_json = summary.model_dump_json()
    assert isinstance(summary_json, str)

    # Required fields should be in the dict
    assert "id" in summary_dict
    assert "user_id" in summary_dict
    assert "session_id" in summary_dict
    assert "title" in summary_dict
    assert "completion_status" in summary_dict
    assert "full_analysis" in summary_dict
    assert "summary_version" in summary_dict
