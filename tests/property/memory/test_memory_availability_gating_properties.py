"""Property-based tests for memory availability gating.

Feature: proxy-mem
Property: 1
Validates: Requirements 1.2, 2.4 - Memory availability gates all activation
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.memory.config import MemoryConfiguration
from src.core.memory.service import MemoryService
from src.core.memory.sqlite_repository import MemoryRepository


@pytest.mark.asyncio
@given(
    user_id=st.text(
        min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
    ),
    session_id=st.text(
        min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
    ),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_1_unavailable_memory_blocks_all_enable(
    user_id: str,
    session_id: str,
) -> None:
    """
    Property 1: When memory is globally unavailable, all enable attempts fail.

    Validates: Requirements 1.2, 2.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=False,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        assert service.is_available() is False

        result = await service.enable_for_session(session_id, user_id)
        assert result is False

        assert await service.is_enabled_for_session(session_id) is False


@pytest.mark.asyncio
@given(
    user_id=st.text(
        min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"
    ),
    session_id=st.text(
        min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-"
    ),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_1_available_memory_allows_enable(
    user_id: str,
    session_id: str,
) -> None:
    """
    Property 1: When memory is globally available, enable attempts can succeed.

    Validates: Requirements 1.2
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        assert service.is_available() is True

        result = await service.enable_for_session(session_id, user_id)
        assert result is True

        assert await service.is_enabled_for_session(session_id) is True


@pytest.mark.asyncio
@given(
    denied_user=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"),
    other_user=st.text(min_size=1, max_size=20, alphabet="0123456789"),
)
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_1_denied_user_blocked(
    denied_user: str,
    other_user: str,
) -> None:
    """
    Property 1: Users in deny list cannot enable memory.

    Validates: Requirements 2.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            disabled_users=[denied_user],
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Denied user should fail
        result1 = await service.enable_for_session("sess-1", denied_user)
        assert result1 is False

        # Other user should succeed
        result2 = await service.enable_for_session("sess-2", other_user)
        assert result2 is True


@pytest.mark.asyncio
@given(
    denied_client=st.text(
        min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"
    ),
    other_client=st.text(min_size=1, max_size=20, alphabet="0123456789"),
)
@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_property_1_denied_client_blocked(
    denied_client: str,
    other_client: str,
) -> None:
    """
    Property 1: Clients in deny list cannot enable memory.

    Validates: Requirements 2.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            disabled_clients=[denied_client],
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Denied client should fail
        result1 = await service.enable_for_session(
            "sess-1", "user-1", client_id=denied_client
        )
        assert result1 is False

        # Other client should succeed
        result2 = await service.enable_for_session(
            "sess-2", "user-1", client_id=other_client
        )
        assert result2 is True


@pytest.mark.asyncio
async def test_property_1_missing_user_id_in_multiuser_mode() -> None:
    """
    Property 1: Missing user_id in multi-user mode fails closed.

    Validates: Requirements 2.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            single_user_mode=False,
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Empty user_id should fail
        result = await service.enable_for_session("sess-1", "")
        assert result is False


@pytest.mark.asyncio
async def test_property_1_single_user_mode_allows_empty_user() -> None:
    """
    Property 1: Single-user mode allows empty user_id.

    Validates: Requirements 2.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite3"
        config = MemoryConfiguration(
            available=True,
            database_path=str(db_path),
            single_user_mode=True,
            fixed_user_id="local-user",
            require_project_discovery=False,
        )
        repo = MemoryRepository(config)
        service = MemoryService(config, repo)

        # Empty user_id should succeed in single-user mode
        result = await service.enable_for_session("sess-1", "")
        assert result is True
