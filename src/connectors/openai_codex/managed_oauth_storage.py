"""Storage service for managed OpenAI Codex OAuth accounts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from src.connectors.openai_codex.managed_oauth_models import (
    ManagedOAuthAccount,
    ManagedOAuthAccountSummary,
)

logger = logging.getLogger(__name__)


class ManagedOAuthStorageService:
    """Directory-based storage with one JSON file per account."""

    def __init__(self, storage_path: Path | str) -> None:
        self._storage_path = Path(storage_path)

    @property
    def storage_path(self) -> Path:
        return self._storage_path

    def _account_path(self, account_id: str) -> Path:
        return self._storage_path / f"{account_id}.json"

    def _ensure_storage_dir_sync(self) -> None:
        self._storage_path.mkdir(parents=True, exist_ok=True)

    async def _ensure_storage_dir(self) -> None:
        await asyncio.to_thread(self._ensure_storage_dir_sync)

    def _iter_account_files_sync(self) -> list[Path]:
        if not self._storage_path.exists():
            return []
        return sorted(
            [
                path
                for path in self._storage_path.iterdir()
                if path.is_file() and path.suffix == ".json"
            ],
            key=lambda item: item.name,
        )

    async def has_configured_accounts(self) -> bool:
        """Return True if at least one account file exists."""
        await self._ensure_storage_dir()
        files = await asyncio.to_thread(self._iter_account_files_sync)
        return len(files) > 0

    async def load_all_accounts(self) -> list[ManagedOAuthAccount]:
        """Load and validate all account files."""
        await self._ensure_storage_dir()
        files = await asyncio.to_thread(self._iter_account_files_sync)
        loaded: list[ManagedOAuthAccount] = []
        for file_path in files:
            try:
                raw = await asyncio.to_thread(file_path.read_text, "utf-8")
                parsed = json.loads(raw)
                account = ManagedOAuthAccount.model_validate(parsed)
                loaded.append(account)
            except Exception as exc:
                logger.warning(
                    "Skipping invalid managed OAuth account file %s: %s",
                    file_path,
                    exc,
                    exc_info=True,
                )
        return loaded

    async def get_account(self, account_id: str) -> ManagedOAuthAccount | None:
        """Load a single account by id."""
        path = self._account_path(account_id)
        if not path.exists():
            return None
        try:
            raw = await asyncio.to_thread(path.read_text, "utf-8")
            return ManagedOAuthAccount.model_validate_json(raw)
        except Exception as exc:
            logger.warning(
                "Failed to read managed OAuth account %s: %s",
                account_id,
                exc,
                exc_info=True,
            )
            return None

    def _write_atomic_sync(self, path: Path, content: str, account_id: str) -> None:
        self._ensure_storage_dir_sync()
        fd, temp_path = tempfile.mkstemp(
            dir=self._storage_path,
            prefix=f"{account_id}_",
            suffix=".tmp",
            text=True,
        )
        try:
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise
            if platform.system() != "Windows":
                os.chmod(temp_path, 0o600)
            os.replace(temp_path, str(path))
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise

    async def save_account(self, account: ManagedOAuthAccount) -> None:
        """Persist account atomically."""
        path = self._account_path(account.account_id)
        payload = account.model_dump_json(indent=2)
        await asyncio.to_thread(
            self._write_atomic_sync,
            path,
            payload,
            account.account_id,
        )

    async def delete_account(self, account_id: str) -> bool:
        """Delete account file; return False when account is not found."""
        path = self._account_path(account_id)
        if not path.exists():
            return False
        try:
            await asyncio.to_thread(path.unlink)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to delete managed OAuth account %s: %s",
                account_id,
                exc,
                exc_info=True,
            )
            return False

    async def list_accounts(self) -> list[ManagedOAuthAccountSummary]:
        """List display summaries for all stored accounts."""
        accounts = await self.load_all_accounts()
        return [ManagedOAuthAccountSummary.from_account(account) for account in accounts]

