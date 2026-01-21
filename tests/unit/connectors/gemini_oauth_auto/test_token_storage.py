"""
Unit tests for TokenStorageService.

Tests Requirement 2: Token Storage and Persistence.
"""

import json
import tempfile
from pathlib import Path

import pytest

from src.connectors.gemini_oauth_auto.models import StoredAccount
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService


@pytest.fixture
def temp_storage_dir(tmp_path: Path) -> Path:
    """Fixture providing a temporary storage directory."""
    storage_dir = tmp_path / "gemini_oauth_accounts"
    return storage_dir


@pytest.fixture
def storage_service(temp_storage_dir: Path) -> TokenStorageService:
    """Fixture providing TokenStorageService with temp directory."""
    return TokenStorageService(storage_path=temp_storage_dir)


@pytest.fixture
def valid_account() -> StoredAccount:
    """Fixture providing a valid StoredAccount."""
    import time

    return StoredAccount(
        account_id="test-account",
        email="test@gmail.com",
        access_token="ya29.test_access_token",
        refresh_token="1//test_refresh_token",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((time.time() + 3600) * 1000),
    )


class TestTokenStorageService:
    """Tests for TokenStorageService."""

    @pytest.mark.asyncio
    async def test_directory_auto_creation(
        self, storage_service: TokenStorageService, temp_storage_dir: Path
    ) -> None:
        """Test storage directory is created if missing."""
        assert not temp_storage_dir.exists()

        await storage_service.load_all_accounts()

        assert temp_storage_dir.exists()
        assert temp_storage_dir.is_dir()

    @pytest.mark.asyncio
    async def test_save_account_creates_file(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test save_account creates JSON file."""
        await storage_service.save_account(valid_account)

        expected_file = temp_storage_dir / f"{valid_account.account_id}.json"
        assert expected_file.exists()

    @pytest.mark.asyncio
    async def test_save_account_writes_valid_json(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test save_account writes valid JSON content."""
        await storage_service.save_account(valid_account)

        file_path = temp_storage_dir / f"{valid_account.account_id}.json"
        content = json.loads(file_path.read_text())

        assert content["account_id"] == valid_account.account_id
        assert content["email"] == valid_account.email
        assert content["access_token"] == valid_account.access_token
        assert content["refresh_token"] == valid_account.refresh_token

    @pytest.mark.asyncio
    async def test_save_account_atomic_write(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test save_account uses atomic write (temp file + rename).

        We can't easily test atomicity directly, but we verify that after
        save, there's exactly one file with the expected name.
        """
        await storage_service.save_account(valid_account)

        files = list(temp_storage_dir.glob("*.json"))
        assert len(files) == 1
        assert files[0].name == f"{valid_account.account_id}.json"

        # No temp files should remain
        temp_files = list(temp_storage_dir.glob("*.tmp"))
        assert len(temp_files) == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not hasattr(__import__("os"), "chmod"),
        reason="OS doesn't support chmod",
    )
    async def test_save_account_sets_permissions_posix(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test save_account sets restrictive permissions on POSIX."""
        import os
        import platform

        if platform.system() == "Windows":
            pytest.skip("POSIX permissions test not applicable on Windows")

        await storage_service.save_account(valid_account)

        file_path = temp_storage_dir / f"{valid_account.account_id}.json"
        mode = os.stat(file_path).st_mode & 0o777
        assert mode == 0o600

    @pytest.mark.asyncio
    async def test_get_account_returns_saved_account(
        self,
        storage_service: TokenStorageService,
        valid_account: StoredAccount,
    ) -> None:
        """Test get_account returns previously saved account."""
        await storage_service.save_account(valid_account)

        retrieved = await storage_service.get_account(valid_account.account_id)

        assert retrieved is not None
        assert retrieved.account_id == valid_account.account_id
        assert retrieved.email == valid_account.email
        assert retrieved.access_token == valid_account.access_token

    @pytest.mark.asyncio
    async def test_get_account_returns_none_for_missing(
        self, storage_service: TokenStorageService
    ) -> None:
        """Test get_account returns None for non-existent account."""
        retrieved = await storage_service.get_account("nonexistent-account")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_load_all_accounts_empty_directory(
        self, storage_service: TokenStorageService
    ) -> None:
        """Test load_all_accounts returns empty list for empty directory."""
        accounts = await storage_service.load_all_accounts()
        assert accounts == []

    @pytest.mark.asyncio
    async def test_load_all_accounts_loads_valid_files(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
    ) -> None:
        """Test load_all_accounts loads all valid account files."""
        import time

        # Create two accounts
        account1 = StoredAccount(
            account_id="account-1",
            email="user1@gmail.com",
            access_token="token1",
            refresh_token="refresh1",
            scope="scope",
            expiry_date=int((time.time() + 3600) * 1000),
        )
        account2 = StoredAccount(
            account_id="account-2",
            email="user2@gmail.com",
            access_token="token2",
            refresh_token="refresh2",
            scope="scope",
            expiry_date=int((time.time() + 3600) * 1000),
        )

        await storage_service.save_account(account1)
        await storage_service.save_account(account2)

        accounts = await storage_service.load_all_accounts()

        assert len(accounts) == 2
        account_ids = {a.account_id for a in accounts}
        assert account_ids == {"account-1", "account-2"}

    @pytest.mark.asyncio
    async def test_load_all_accounts_skips_corrupted_files(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test load_all_accounts skips corrupted files with warning."""
        # Save valid account
        await storage_service.save_account(valid_account)

        # Create corrupted file
        corrupted_file = temp_storage_dir / "corrupted.json"
        corrupted_file.write_text("not valid json {{{")

        accounts = await storage_service.load_all_accounts()

        # Should only load valid account
        assert len(accounts) == 1
        assert accounts[0].account_id == valid_account.account_id

        # Should log warning about corrupted file
        assert "corrupted" in caplog.text.lower() or "error" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_load_all_accounts_skips_non_json_files(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test load_all_accounts ignores non-JSON files."""
        await storage_service.save_account(valid_account)

        # Create non-JSON file
        temp_storage_dir.mkdir(parents=True, exist_ok=True)
        (temp_storage_dir / "notes.txt").write_text("Some notes")
        (temp_storage_dir / "README").write_text("README content")

        accounts = await storage_service.load_all_accounts()

        assert len(accounts) == 1
        assert accounts[0].account_id == valid_account.account_id

    @pytest.mark.asyncio
    async def test_delete_account_removes_file(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test delete_account removes the account file."""
        await storage_service.save_account(valid_account)
        file_path = temp_storage_dir / f"{valid_account.account_id}.json"
        assert file_path.exists()

        result = await storage_service.delete_account(valid_account.account_id)

        assert result is True
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_account_returns_false_for_missing(
        self, storage_service: TokenStorageService
    ) -> None:
        """Test delete_account returns False for non-existent account."""
        result = await storage_service.delete_account("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_accounts_returns_summaries(
        self,
        storage_service: TokenStorageService,
        valid_account: StoredAccount,
    ) -> None:
        """Test list_accounts returns AccountSummary list."""
        await storage_service.save_account(valid_account)

        summaries = await storage_service.list_accounts()

        assert len(summaries) == 1
        assert summaries[0].account_id == valid_account.account_id
        assert summaries[0].email == valid_account.email
        assert summaries[0].status == "valid"

    @pytest.mark.asyncio
    async def test_list_accounts_empty_returns_empty_list(
        self, storage_service: TokenStorageService
    ) -> None:
        """Test list_accounts returns empty list when no accounts."""
        summaries = await storage_service.list_accounts()
        assert summaries == []

    @pytest.mark.asyncio
    async def test_save_account_updates_existing(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        """Test save_account overwrites existing account file."""
        await storage_service.save_account(valid_account)

        # Update account with new token
        updated = valid_account.with_updated_tokens(
            access_token="new_access_token",
            expiry_date=valid_account.expiry_date + 3600000,
        )
        await storage_service.save_account(updated)

        # Verify updated values
        retrieved = await storage_service.get_account(valid_account.account_id)
        assert retrieved is not None
        assert retrieved.access_token == "new_access_token"

        # Should still be only one file
        files = list(temp_storage_dir.glob("*.json"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_save_account_with_special_account_id(
        self, storage_service: TokenStorageService, temp_storage_dir: Path
    ) -> None:
        """Test save_account handles account IDs with allowed special chars."""
        import time

        account = StoredAccount(
            account_id="my-account_123",
            email="test@gmail.com",
            access_token="token",
            refresh_token="refresh",
            scope="scope",
            expiry_date=int((time.time() + 3600) * 1000),
        )

        await storage_service.save_account(account)

        file_path = temp_storage_dir / "my-account_123.json"
        assert file_path.exists()

        # Round-trip verification
        retrieved = await storage_service.get_account("my-account_123")
        assert retrieved is not None
        assert retrieved.account_id == "my-account_123"
