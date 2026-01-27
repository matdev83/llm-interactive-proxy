"""
Unit tests for Kiro TokenStorageService.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from freezegun import freeze_time
from src.connectors.kiro_oauth_auto.models import StoredAccount
from src.connectors.kiro_oauth_auto.token_storage import TokenStorageService

# Matches @freeze_time("2026-01-19")
BASE_TIME = 1768780800.0  # 2026-01-19 00:00:00 UTC


@pytest.fixture
def temp_storage_dir(tmp_path: Path) -> Path:
    return tmp_path / "kiro_oauth_accounts"


@pytest.fixture
def storage_service(temp_storage_dir: Path) -> TokenStorageService:
    return TokenStorageService(storage_path=temp_storage_dir)


@pytest.fixture
def valid_account() -> StoredAccount:
    return StoredAccount(
        account_id="test-account",
        auth_method="builderid",
        region="us-east-1",
        access_token="access.test",
        refresh_token="refresh.test",
        client_id="client.test",
        client_secret="secret.test",
        expiry_date=int((BASE_TIME + 3600) * 1000),
    )


@freeze_time("2026-01-19")
class TestTokenStorageService:
    @pytest.mark.asyncio
    async def test_directory_auto_creation(
        self, storage_service: TokenStorageService, temp_storage_dir: Path
    ) -> None:
        assert not temp_storage_dir.exists()
        await storage_service.load_all_accounts()
        assert temp_storage_dir.exists()
        assert temp_storage_dir.is_dir()

    @pytest.mark.asyncio
    async def test_save_and_get_roundtrip(
        self, storage_service: TokenStorageService, valid_account: StoredAccount
    ) -> None:
        await storage_service.save_account(valid_account)
        loaded = await storage_service.get_account(valid_account.account_id)
        assert loaded is not None
        assert loaded.account_id == valid_account.account_id
        assert loaded.access_token == valid_account.access_token
        assert loaded.refresh_token == valid_account.refresh_token

    @pytest.mark.asyncio
    async def test_save_writes_json(
        self,
        storage_service: TokenStorageService,
        temp_storage_dir: Path,
        valid_account: StoredAccount,
    ) -> None:
        await storage_service.save_account(valid_account)
        file_path = temp_storage_dir / f"{valid_account.account_id}.json"
        data = json.loads(file_path.read_text(encoding="utf-8"))
        assert data["account_id"] == valid_account.account_id
        assert data["client_id"] == valid_account.client_id

    @pytest.mark.asyncio
    async def test_load_all_skips_invalid_json(
        self, storage_service: TokenStorageService, temp_storage_dir: Path
    ) -> None:
        temp_storage_dir.mkdir(parents=True, exist_ok=True)
        (temp_storage_dir / "bad.json").write_text("{not valid json}", encoding="utf-8")
        accounts = await storage_service.load_all_accounts()
        assert accounts == []

    @pytest.mark.asyncio
    async def test_delete_account(
        self, storage_service: TokenStorageService, valid_account: StoredAccount
    ) -> None:
        await storage_service.save_account(valid_account)
        assert await storage_service.delete_account(valid_account.account_id) is True
        assert await storage_service.get_account(valid_account.account_id) is None
        assert await storage_service.delete_account(valid_account.account_id) is False

    @pytest.mark.asyncio
    async def test_list_accounts(
        self, storage_service: TokenStorageService, valid_account: StoredAccount
    ) -> None:
        await storage_service.save_account(valid_account)
        summaries = await storage_service.list_accounts()
        assert len(summaries) == 1
        assert summaries[0].account_id == valid_account.account_id
        assert summaries[0].status == "valid"
