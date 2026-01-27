"""Token storage for Kiro OAuth auto-connector."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from src.connectors.kiro_oauth_auto.constants import DEFAULT_STORAGE_PATH
from src.connectors.kiro_oauth_auto.models import AccountSummary, StoredAccount

logger = logging.getLogger(__name__)


class TokenStorageService:
    """Stores Kiro OAuth accounts in a directory with one JSON file per account."""

    def __init__(self, storage_path: Path | str | None = None) -> None:
        if storage_path is None:
            self._storage_path = Path(DEFAULT_STORAGE_PATH)
        elif isinstance(storage_path, str):
            self._storage_path = Path(storage_path)
        else:
            self._storage_path = storage_path

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def _get_account_path(self, account_id: str) -> Path:
        return self._storage_path / f"{account_id}.json"

    def _ensure_directory_exists_sync(self) -> None:
        self._storage_path.mkdir(parents=True, exist_ok=True)

    def _read_file_sync(self, file_path: Path) -> str | None:
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("Error reading file %s: %s", file_path, exc, exc_info=True)
            return None

    def _write_file_atomic_sync(
        self, file_path: Path, content: str, account_id: str
    ) -> None:
        self._ensure_directory_exists_sync()

        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f"{account_id}_",
            dir=self._storage_path,
        )

        try:
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise

            if platform.system() != "Windows":
                os.chmod(temp_path, 0o600)

            if platform.system() == "Windows" and file_path.exists():
                file_path.unlink()

            Path(temp_path).rename(file_path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise

    async def load_all_accounts(self) -> list[StoredAccount]:
        await asyncio.to_thread(self._ensure_directory_exists_sync)
        if not self._storage_path.exists():
            return []

        files = [
            p
            for p in self._storage_path.iterdir()
            if p.is_file() and p.suffix == ".json"
        ]
        accounts: list[StoredAccount] = []

        for file_path in files:
            try:
                content = await asyncio.to_thread(self._read_file_sync, file_path)
                if content is None:
                    continue
                data = json.loads(content)
                accounts.append(StoredAccount.model_validate(data))
            except Exception as exc:
                logger.warning(
                    "Skipping invalid account file %s: %s",
                    file_path.name,
                    exc,
                    exc_info=True,
                )
        return accounts

    async def get_account(self, account_id: str) -> StoredAccount | None:
        file_path = self._get_account_path(account_id)
        if not file_path.exists():
            return None
        try:
            content = await asyncio.to_thread(self._read_file_sync, file_path)
            if content is None:
                return None
            data = json.loads(content)
            return StoredAccount.model_validate(data)
        except Exception as exc:
            logger.warning(
                "Error reading account %s: %s", account_id, exc, exc_info=True
            )
            return None

    async def save_account(self, account: StoredAccount) -> None:
        file_path = self._get_account_path(account.account_id)
        payload = account.model_dump_json(indent=2)
        await asyncio.to_thread(
            self._write_file_atomic_sync, file_path, payload, account.account_id
        )

    async def delete_account(self, account_id: str) -> bool:
        """Delete account credentials file."""
        file_path = self._get_account_path(account_id)
        if not file_path.exists():
            return False
        try:
            await asyncio.to_thread(file_path.unlink)
            return True
        except OSError as exc:
            logger.error("Failed to delete account %s: %s", account_id, exc)
            return False

    async def list_accounts(self) -> list[AccountSummary]:
        """List all accounts with status information."""
        accounts = await self.load_all_accounts()
        return [AccountSummary.from_stored_account(acc) for acc in accounts]
