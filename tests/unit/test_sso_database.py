"""Unit tests for SSO database operations."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from freezegun import freeze_time
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.models import TokenRecord
from src.core.auth.sso.token_service import TokenService


@pytest.fixture
def temp_db_path():
    """Fixture for temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


@pytest.fixture
async def initialized_db(temp_db_path):
    """Fixture for initialized database."""
    db_manager = DatabaseManager(temp_db_path)
    await db_manager.initialize_schema()
    return temp_db_path


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_find_by_user_id_returns_token_for_existing_user(initialized_db):
    """Test that find_by_user_id returns token for existing user."""
    # Setup
    token_service = TokenService.create_for_environment()
    token_repository = TokenRepository(initialized_db)

    # Create a token for a user
    plaintext_token, token_hash = token_service.generate_token()
    user_id = "test-user-123"
    frozen_time = datetime.now(timezone.utc)
    token_record = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash,
        user_id=user_id,
        user_email="test@example.com",
        provider="google",
        is_authenticated=True,
        is_active=True,
        created_at=frozen_time,
        last_authenticated_at=frozen_time,
        auth_expires_at=frozen_time + timedelta(hours=24),
    )
    await token_repository.store_token(token_record)

    # Execute
    found_token = await token_repository.find_by_user_id(user_id)

    # Verify
    assert found_token is not None
    assert found_token.user_id == user_id
    assert found_token.id == token_record.id
    assert found_token.token_hash == token_hash


@pytest.mark.asyncio
async def test_find_by_user_id_returns_none_for_nonexistent_user(initialized_db):
    """Test that find_by_user_id returns None for non-existent user."""
    # Setup
    token_repository = TokenRepository(initialized_db)

    # Execute
    found_token = await token_repository.find_by_user_id("nonexistent-user")

    # Verify
    assert found_token is None


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_find_by_user_id_returns_most_recent_token(initialized_db):
    """Test that find_by_user_id returns the most recent token when multiple exist."""
    # Setup
    token_service = TokenService.create_for_environment()
    token_repository = TokenRepository(initialized_db)

    user_id = "test-user-456"

    # Create two tokens for the same user at different times
    frozen_time = datetime.now(timezone.utc)
    plaintext_token1, token_hash1 = token_service.generate_token()
    token_record1 = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash1,
        user_id=user_id,
        user_email="test@example.com",
        provider="google",
        is_authenticated=True,
        is_active=True,
        created_at=frozen_time - timedelta(hours=2),  # Older
        last_authenticated_at=frozen_time - timedelta(hours=2),
        auth_expires_at=frozen_time + timedelta(hours=22),
    )
    await token_repository.store_token(token_record1)

    plaintext_token2, token_hash2 = token_service.generate_token()
    token_record2 = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash2,
        user_id=user_id,
        user_email="test@example.com",
        provider="google",
        is_authenticated=True,
        is_active=True,
        created_at=frozen_time,  # Newer
        last_authenticated_at=frozen_time,
        auth_expires_at=frozen_time + timedelta(hours=24),
    )
    await token_repository.store_token(token_record2)

    # Execute
    found_token = await token_repository.find_by_user_id(user_id)

    # Verify - should return the most recent token
    assert found_token is not None
    assert found_token.id == token_record2.id
    assert found_token.token_hash == token_hash2


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_find_by_user_id_ignores_inactive_tokens(initialized_db):
    """Test that find_by_user_id ignores inactive tokens."""
    # Setup
    token_service = TokenService.create_for_environment()
    token_repository = TokenRepository(initialized_db)

    user_id = "test-user-789"

    # Create an inactive token
    frozen_time = datetime.now(timezone.utc)
    plaintext_token, token_hash = token_service.generate_token()
    token_record = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash,
        user_id=user_id,
        user_email="test@example.com",
        provider="google",
        is_authenticated=True,
        is_active=False,  # Inactive
        created_at=frozen_time,
        last_authenticated_at=frozen_time,
        auth_expires_at=frozen_time + timedelta(hours=24),
    )
    await token_repository.store_token(token_record)

    # Execute
    found_token = await token_repository.find_by_user_id(user_id)

    # Verify - should not find inactive token
    assert found_token is None


@pytest.mark.asyncio
@freeze_time("2024-01-01 12:00:00")
async def test_reauthentication_updates_existing_token(initialized_db):
    """Test that re-authentication updates existing token instead of creating new one."""
    # Setup
    token_service = TokenService(memory_cost=8192, time_cost=1, parallelism=1)
    token_repository = TokenRepository(initialized_db)

    user_id = "test-user-reauth"

    # Create initial token (expired)
    frozen_time = datetime.now(timezone.utc)
    plaintext_token, token_hash = token_service.generate_token()
    original_token_record = TokenRecord(
        id=str(uuid4()),
        token_hash=token_hash,
        user_id=user_id,
        user_email="test@example.com",
        provider="google",
        is_authenticated=False,  # Expired
        is_active=True,
        created_at=frozen_time - timedelta(hours=25),
        last_authenticated_at=frozen_time - timedelta(hours=25),
        auth_expires_at=frozen_time - timedelta(hours=1),  # Expired
    )
    await token_repository.store_token(original_token_record)

    # Simulate re-authentication
    existing_token = await token_repository.find_by_user_id(user_id)
    assert existing_token is not None

    # Update auth status
    new_expiry = frozen_time + timedelta(hours=24)
    await token_repository.update_auth_status(
        existing_token.id,
        authenticated=True,
        expiry=new_expiry,
    )

    # Verify token was updated, not replaced
    updated_token = await token_repository.find_by_user_id(user_id)
    assert updated_token is not None
    assert updated_token.id == original_token_record.id  # Same token ID
    assert updated_token.token_hash == token_hash  # Same hash
    assert updated_token.is_authenticated is True  # Now authenticated
    assert updated_token.auth_expires_at > frozen_time  # New expiry

    # Verify only one token exists for this user
    all_hashes = await token_repository.get_all_token_hashes()
    assert len(all_hashes) == 1
