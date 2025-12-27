"""Property-based tests for SSO login tokens.

Feature: sso-authentication
Properties: Login Token Lifecycle
"""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from tests.utils.hypothesis_config import property_test_settings


@contextmanager
def temp_db_path():
    """Context manager for temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


@given(ttl_minutes=st.integers(min_value=1, max_value=60))
@property_test_settings(max_examples=10)
def test_login_token_lifecycle(ttl_minutes: int) -> None:
    """Test creation, verification, and consumption of login tokens."""

    async def run_test():
        with temp_db_path() as db_path:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            repo = TokenRepository(db_path)

            # Create token
            token = await repo.create_login_token(ttl_minutes=ttl_minutes)
            assert token is not None
            assert len(token) > 10

            # Verify and consume (first time)
            success, error = await repo.verify_and_consume_login_token(token)
            assert success is True
            assert error is None

            # Verify consumption (second time should fail)
            success, error = await repo.verify_and_consume_login_token(token)
            assert success is False

    asyncio.run(run_test())


@given(
    ttl_minutes=st.integers(min_value=1, max_value=60),
    wait_seconds=st.floats(min_value=0.1, max_value=1.0),
)
@property_test_settings(max_examples=10)
def test_login_token_expiry(ttl_minutes: int, wait_seconds: float) -> None:
    """Test that expired tokens are rejected."""
    # Note: We can't easily wait for minutes in property tests.
    # We'll manually insert an expired token to test expiry logic.

    async def run_test():
        with temp_db_path() as db_path:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            repo = TokenRepository(db_path)

            # Manually insert expired token
            import aiosqlite

            expired_token = "expired-token"
            created_at = datetime.utcnow() - timedelta(minutes=ttl_minutes + 1)
            expires_at = created_at + timedelta(minutes=ttl_minutes)

            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    """
                    INSERT INTO sso_login_tokens (token, created_at, expires_at)
                    VALUES (?, ?, ?)
                    """,
                    (expired_token, created_at.isoformat(), expires_at.isoformat()),
                )
                await db.commit()

            # Verify expired token returns False
            success, error = await repo.verify_and_consume_login_token(expired_token)
            assert success is False

            # Verify it was deleted from DB (cleanup)
            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute(
                    "SELECT * FROM sso_login_tokens WHERE token = ?",
                    (expired_token,),
                )
                assert await cursor.fetchone() is None

    asyncio.run(run_test())
