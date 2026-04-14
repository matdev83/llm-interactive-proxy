"""Unit tests for ManagedOAuthStorageService permission-error resilience.

Covers the scenario where a Windows transient PermissionError (file locked
during concurrent read/write) causes an OAuth account file to be silently
skipped, removing it from the rotation pool.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from src.connectors.openai_codex.managed_oauth_models import ManagedOAuthAccount
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


def _make_account(account_id: str, email: str | None = None) -> ManagedOAuthAccount:
    return ManagedOAuthAccount(
        account_id=account_id,
        access_token=f"token_{account_id}",
        refresh_token=f"refresh_{account_id}",
        email=email,
        expiry_date=9_999_999_999_999,
    )


class TestLoadAllAccountsPermissionRetry:
    """load_all_accounts should retry on transient PermissionError."""

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_permission_error(self, tmp_path: Path) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        account_a = _make_account("acct_a", email="a@example.com")
        account_b = _make_account("acct_b", email="b@example.com")
        await storage.save_account(account_a)
        await storage.save_account(account_b)

        original_read_text = Path.read_text
        call_count = {"acct_a": 0}

        def _patched_read_text(self_path: Path, encoding: str | None = None) -> str:
            if "acct_a" in self_path.name:
                call_count["acct_a"] += 1
                if call_count["acct_a"] == 1:
                    raise PermissionError(f"[Errno 13] Permission denied: {self_path}")
                return original_read_text(self_path, encoding=encoding)
            return original_read_text(self_path, encoding=encoding)

        with patch.object(Path, "read_text", _patched_read_text):
            accounts = await storage.load_all_accounts()

        ids = {a.account_id for a in accounts}
        assert "acct_a" in ids, "acct_a should be loaded after transient PermissionError"
        assert "acct_b" in ids
        assert call_count["acct_a"] == 2, "acct_a should have been retried once"

    @pytest.mark.asyncio
    async def test_skips_file_after_persistent_permission_error(
        self, tmp_path: Path
    ) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        account_a = _make_account("acct_a", email="a@example.com")
        await storage.save_account(account_a)

        def _always_permission_error(self_path: Path, encoding: str | None = None) -> str:
            raise PermissionError(f"[Errno 13] Permission denied: {self_path}")

        with patch.object(Path, "read_text", _always_permission_error):
            accounts = await storage.load_all_accounts()

        assert len(accounts) == 0, "Persistently locked file should be skipped"

    @pytest.mark.asyncio
    async def test_partial_permission_error_preserves_other_accounts(
        self, tmp_path: Path
    ) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        account_a = _make_account("acct_a", email="a@example.com")
        account_b = _make_account("acct_b", email="b@example.com")
        account_c = _make_account("acct_c", email="c@example.com")
        await storage.save_account(account_a)
        await storage.save_account(account_b)
        await storage.save_account(account_c)

        original_read_text = Path.read_text

        def _patched_read_text(self_path: Path, encoding: str | None = None) -> str:
            if "acct_b" in self_path.name:
                raise PermissionError(f"[Errno 13] Permission denied: {self_path}")
            return original_read_text(self_path, encoding=encoding)

        with patch.object(Path, "read_text", _patched_read_text):
            accounts = await storage.load_all_accounts()

        ids = {a.account_id for a in accounts}
        assert "acct_a" in ids, "acct_a should still be loaded"
        assert "acct_c" in ids, "acct_c should still be loaded"
        assert "acct_b" not in ids, "acct_b should be skipped after persistent PermissionError"


class TestGetAccountPermissionRetry:
    """get_account should retry on transient PermissionError."""

    @pytest.mark.asyncio
    async def test_get_account_retries_on_transient_permission_error(
        self, tmp_path: Path
    ) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        account = _make_account("acct_a", email="a@example.com")
        await storage.save_account(account)

        original_read_text = Path.read_text
        call_count = {"acct_a": 0}

        def _patched_read_text(self_path: Path, encoding: str | None = None) -> str:
            if "acct_a" in self_path.name:
                call_count["acct_a"] += 1
                if call_count["acct_a"] == 1:
                    raise PermissionError(f"[Errno 13] Permission denied: {self_path}")
                return original_read_text(self_path, encoding=encoding)
            return original_read_text(self_path, encoding=encoding)

        with patch.object(Path, "read_text", _patched_read_text):
            result = await storage.get_account("acct_a")

        assert result is not None
        assert result.account_id == "acct_a"
        assert call_count["acct_a"] == 2

    @pytest.mark.asyncio
    async def test_get_account_returns_none_after_persistent_permission_error(
        self, tmp_path: Path
    ) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        account = _make_account("acct_a", email="a@example.com")
        await storage.save_account(account)

        def _always_permission_error(self_path: Path, encoding: str | None = None) -> str:
            raise PermissionError(f"[Errno 13] Permission denied: {self_path}")

        with patch.object(Path, "read_text", _always_permission_error):
            result = await storage.get_account("acct_a")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_account_returns_none_for_nonexistent_file(
        self, tmp_path: Path
    ) -> None:
        storage = ManagedOAuthStorageService(tmp_path)
        result = await storage.get_account("nonexistent")
        assert result is None