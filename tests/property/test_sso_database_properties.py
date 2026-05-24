"""Property-based tests for SSO database operations.

Feature: sso-authentication
Properties: 24, 14
Validates: Requirements 8.5, 5.4
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from freezegun import freeze_time
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.models import TokenRecord
from tests.utils.hypothesis_config import (
    slow_property_test_settings,
)

# Strategy for generating valid datetime objects
datetime_strategy = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2023, 1, 1),
)


# Strategy for generating valid TokenRecord instances with real hashes
@st.composite
def token_record_with_plaintext_strategy(draw: st.DrawFn) -> tuple[TokenRecord, str]:
    """Generate valid TokenRecord instances using real TokenService hashing.

    Returns:
        Tuple of (TokenRecord, plaintext_token)
    """
    from src.core.auth.sso.token_service import TokenService

    service = TokenService.create_for_environment()
    plaintext_token, token_hash = service.generate_token()

    created_at = draw(datetime_strategy)
    last_authenticated_at = draw(
        st.one_of(
            st.just(created_at),
            st.datetimes(
                min_value=created_at,
                max_value=created_at + timedelta(days=365),
            ),
        )
    )

    # auth_expires_at can be None or a future datetime
    auth_expires_at = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=last_authenticated_at,
                max_value=last_authenticated_at + timedelta(days=30),
            ),
        )
    )

    token_record = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash,  # Use real hash from TokenService
        user_id=draw(st.text(min_size=1, max_size=100)),
        user_email=draw(st.emails()),
        provider=draw(
            st.sampled_from(
                [
                    "google",
                    "microsoft",
                    "github",
                    "linkedin",
                    "aws-iam-ic",
                ]
            )
        ),
        is_authenticated=draw(st.booleans()),
        is_active=True,  # Always start as active
        created_at=created_at,
        last_authenticated_at=last_authenticated_at,
        auth_expires_at=auth_expires_at,
    )

    return token_record, plaintext_token


async def create_temp_database():
    """Create a temporary database for testing."""
    # Create temporary directory
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_sso.db")

    # Initialize database
    db_manager = DatabaseManager(db_path)
    await db_manager.initialize_schema()

    return db_path, temp_dir


async def cleanup_temp_database(db_path: str, temp_dir: str):
    """Cleanup temporary database."""
    try:
        Path(db_path).unlink(missing_ok=True)
        Path(temp_dir).rmdir()
    except Exception:
        pass


@given(token_data=token_record_with_plaintext_strategy())
@slow_property_test_settings()  # Reduced iterations for database I/O
@pytest.mark.asyncio
@pytest.mark.slow  # Uses database and real crypto
async def test_property_24_token_soft_delete(
    token_data: tuple[TokenRecord, str],
) -> None:
    """
    Property 24: Token Soft Delete.

    For any revoked or expired token, the database record SHALL be marked as
    inactive (is_active=false) rather than deleted.

    Validates: Requirements 8.5

    Feature: sso-authentication, Property 24: Token Soft Delete
    """
    token_record, plaintext_token = token_data

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        repository = TokenRepository(temp_database)

        # Store the token
        await repository.store_token(token_record)

        # Verify token exists and is active
        found_token = await repository.find_by_hash(token_record.token_hash)
        assert found_token is not None
        assert found_token.is_active is True

        # Revoke the token
        await repository.revoke_token(token_record.id)

        # Verify token still exists in database but is marked inactive
        # We need to query directly to see inactive tokens
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, is_active
                FROM agent_tokens
                WHERE id = ?
                """,
                (token_record.id,),
            )
            row = await cursor.fetchone()

            # Token record should still exist
            assert row is not None
            assert row["id"] == token_record.id

            # Token should be marked as inactive (soft delete)
            assert row["is_active"] == 0  # SQLite stores boolean as 0/1

        # Verify find_by_hash no longer returns the revoked token
        # (because it only returns active tokens)
        found_after_revoke = await repository.find_by_hash(token_record.token_hash)
        assert found_after_revoke is None
    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    token_data_list=st.lists(
        token_record_with_plaintext_strategy(),
        min_size=2,
        max_size=5,
    )
)
@slow_property_test_settings()  # Reduced iterations for database I/O
@pytest.mark.asyncio
@pytest.mark.slow  # Uses database and real crypto
async def test_property_24_multiple_tokens_soft_delete(
    token_data_list: list[tuple[TokenRecord, str]],
) -> None:
    """
    Property 24: Multiple tokens soft delete.

    For any collection of tokens, when some are revoked, all revoked tokens
    SHALL remain in the database marked as inactive.

    Validates: Requirements 8.5

    Feature: sso-authentication, Property 24: Token Soft Delete
    """
    # Unpack token records from tuples
    token_records = [record for record, _ in token_data_list]

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        repository = TokenRepository(temp_database)

        # Store all tokens
        for token_record in token_records:
            await repository.store_token(token_record)

        # Revoke half of the tokens (at least one)
        tokens_to_revoke = token_records[: len(token_records) // 2 + 1]
        tokens_to_keep = token_records[len(token_records) // 2 + 1 :]

        for token_record in tokens_to_revoke:
            await repository.revoke_token(token_record.id)

        # Verify all tokens still exist in database
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM agent_tokens")
            row = await cursor.fetchone()
            assert row[0] == len(token_records)

        # Verify revoked tokens are marked inactive
        async with aiosqlite.connect(temp_database) as db:
            for token_record in tokens_to_revoke:
                cursor = await db.execute(
                    "SELECT is_active FROM agent_tokens WHERE id = ?",
                    (token_record.id,),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 0  # Inactive

        # Verify non-revoked tokens are still active
        async with aiosqlite.connect(temp_database) as db:
            for token_record in tokens_to_keep:
                cursor = await db.execute(
                    "SELECT is_active FROM agent_tokens WHERE id = ?",
                    (token_record.id,),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 1  # Active
    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(token_data=token_record_with_plaintext_strategy())
@slow_property_test_settings()  # Reduced iterations for database I/O
@pytest.mark.asyncio
@pytest.mark.slow  # Uses database and time.sleep
async def test_property_14_database_status_synchronization(
    token_data: tuple[TokenRecord, str],
) -> None:
    """
    Property 14: Database Status Synchronization.

    For any authentication status change (authenticated to unauthenticated or
    vice versa), the SQLite database record SHALL be updated with the new
    status and a current timestamp.

    Validates: Requirements 5.4

    Feature: sso-authentication, Property 14: Database Status Synchronization
    """
    token_record, _ = token_data

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        repository = TokenRepository(temp_database)

        # Store the token with initial authentication status
        initial_auth_status = token_record.is_authenticated
        await repository.store_token(token_record)

        # Get the initial timestamp from database
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT last_authenticated_at FROM agent_tokens WHERE id = ?",
                (token_record.id,),
            )
            row = await cursor.fetchone()
            # Parse and normalize to naive datetime for comparison
            time_before_update = datetime.fromisoformat(
                row["last_authenticated_at"]
            ).replace(tzinfo=None)

        # Use freezegun to advance time instead of sleeping
        with freeze_time() as frozen_time:
            frozen_time.tick(
                delta=timedelta(milliseconds=10)
            )  # Advance time to ensure timestamp difference

            # Change authentication status
            new_auth_status = not initial_auth_status
            new_expiry = (
                datetime.now(timezone.utc) + timedelta(hours=24)
                if new_auth_status
                else None
            )

            await repository.update_auth_status(
                token_record.id,
                new_auth_status,
                new_expiry,
            )

        # Verify the status was updated in the database
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT is_authenticated, last_authenticated_at, auth_expires_at
                FROM agent_tokens
                WHERE id = ?
                """,
                (token_record.id,),
            )
            row = await cursor.fetchone()

            assert row is not None

            # Verify authentication status was updated
            assert bool(row["is_authenticated"]) == new_auth_status

            # Verify timestamp was updated (normalize to naive for comparison)
            last_auth_time = datetime.fromisoformat(
                row["last_authenticated_at"]
            ).replace(tzinfo=None)
            assert last_auth_time >= time_before_update.replace(tzinfo=None)

            # Verify expiry was updated correctly
            if new_expiry:
                stored_expiry = datetime.fromisoformat(row["auth_expires_at"])
                # Normalize both to UTC-aware for comparison
                if stored_expiry.tzinfo is None:
                    stored_expiry = stored_expiry.replace(tzinfo=timezone.utc)
                if new_expiry.tzinfo is None:
                    new_expiry = new_expiry.replace(tzinfo=timezone.utc)
                # Allow small time difference due to serialization
                assert abs((stored_expiry - new_expiry).total_seconds()) < 2
            else:
                assert row["auth_expires_at"] is None
    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(
    token_data=token_record_with_plaintext_strategy(),
    status_changes=st.lists(
        st.booleans(),
        min_size=2,
        max_size=5,
    ),
)
@slow_property_test_settings()  # Reduced iterations for database I/O
@pytest.mark.asyncio
@pytest.mark.slow  # Uses database and time.sleep
async def test_property_14_multiple_status_changes(
    token_data: tuple[TokenRecord, str],
    status_changes: list[bool],
) -> None:
    """
    Property 14: Multiple status changes synchronization.

    For any sequence of authentication status changes, each change SHALL be
    reflected in the database with updated timestamps.

    Validates: Requirements 5.4

    Feature: sso-authentication, Property 14: Database Status Synchronization
    """
    token_record, _ = token_data

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        repository = TokenRepository(temp_database)

        # Store the token
        await repository.store_token(token_record)

        # Get initial timestamp from database
        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT last_authenticated_at FROM agent_tokens WHERE id = ?",
                (token_record.id,),
            )
            row = await cursor.fetchone()
            # Normalize to naive datetime for comparison
            previous_timestamp = datetime.fromisoformat(
                row["last_authenticated_at"]
            ).replace(tzinfo=None)

        # Apply each status change
        with freeze_time() as frozen_time:
            for new_status in status_changes:
                frozen_time.tick(
                    delta=timedelta(milliseconds=10)
                )  # Advance time to ensure timestamp differences
                new_expiry = (
                    datetime.utcnow() + timedelta(hours=24) if new_status else None
                )

                await repository.update_auth_status(
                    token_record.id,
                    new_status,
                    new_expiry,
                )

            # Verify the change was persisted
            import aiosqlite

            async with aiosqlite.connect(temp_database) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT is_authenticated, last_authenticated_at
                    FROM agent_tokens
                    WHERE id = ?
                    """,
                    (token_record.id,),
                )
                row = await cursor.fetchone()

                assert row is not None
                assert bool(row["is_authenticated"]) == new_status

                # Verify timestamp was updated (should be >= previous, normalize for comparison)
                current_timestamp = datetime.fromisoformat(
                    row["last_authenticated_at"]
                ).replace(tzinfo=None)
                assert current_timestamp >= previous_timestamp.replace(tzinfo=None)
                previous_timestamp = current_timestamp
    finally:
        await cleanup_temp_database(temp_database, temp_dir)


@given(token_data=token_record_with_plaintext_strategy())
@slow_property_test_settings()  # Reduced iterations for database I/O
@pytest.mark.asyncio
@pytest.mark.slow  # Uses database and time.sleep
async def test_property_14_timestamp_monotonicity(
    token_data: tuple[TokenRecord, str],
) -> None:
    """
    Property 14: Timestamp monotonicity.

    For any token, the last_authenticated_at timestamp SHALL never decrease
    across status updates.

    Validates: Requirements 5.4

    Feature: sso-authentication, Property 14: Database Status Synchronization
    """
    token_record, _ = token_data

    # Create temporary database for this test
    temp_database, temp_dir = await create_temp_database()

    try:
        repository = TokenRepository(temp_database)

        # Store the token
        await repository.store_token(token_record)

        # Get initial timestamp

        import aiosqlite

        async with aiosqlite.connect(temp_database) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT last_authenticated_at FROM agent_tokens WHERE id = ?",
                (token_record.id,),
            )
            row = await cursor.fetchone()
            # Normalize to naive datetime for comparison
            initial_timestamp = datetime.fromisoformat(
                row["last_authenticated_at"]
            ).replace(tzinfo=None)

        # Perform multiple status updates
        with freeze_time() as frozen_time:
            for _ in range(3):
                frozen_time.tick(
                    delta=timedelta(milliseconds=10)
                )  # Advance time to ensure timestamp increments
                await repository.update_auth_status(
                    token_record.id,
                    True,
                    datetime.now(timezone.utc) + timedelta(hours=24),
                )

                # Verify timestamp never decreases
                async with aiosqlite.connect(temp_database) as db:
                    db.row_factory = aiosqlite.Row
                    cursor = await db.execute(
                        "SELECT last_authenticated_at FROM agent_tokens WHERE id = ?",
                        (token_record.id,),
                    )
                    row = await cursor.fetchone()
                    current_timestamp = datetime.fromisoformat(
                        row["last_authenticated_at"]
                    ).replace(tzinfo=None)

                    # Timestamp should be >= initial timestamp
                    assert current_timestamp >= initial_timestamp.replace(tzinfo=None)
    finally:
        await cleanup_temp_database(temp_database, temp_dir)
