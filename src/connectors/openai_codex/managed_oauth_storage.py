"""Storage service for managed OpenAI Codex OAuth accounts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
import time
from pathlib import Path

from src.connectors.openai_codex.managed_oauth_models import (
    ManagedOAuthAccount,
    ManagedOAuthAccountSummary,
)

logger = logging.getLogger(__name__)

_PERMISSION_ERROR_RETRIES = 3
_PERMISSION_ERROR_BASE_DELAY = 0.05


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

    async def _read_file_with_retry(self, file_path: Path) -> str | None:
        """Read a file, retrying on transient PermissionError (common on Windows).

        On Windows, concurrent read/write of the same file (e.g. during
        atomic replace by :meth:`_write_atomic_sync`) can cause a brief
        ``PermissionError``.  Retrying with a small backoff usually succeeds.

        Returns:
            File content on success, or ``None`` if the file cannot be read
            after all retries.
        """
        last_exc: PermissionError | None = None
        for attempt in range(_PERMISSION_ERROR_RETRIES):
            try:
                return await asyncio.to_thread(file_path.read_text, "utf-8")
            except PermissionError as exc:
                last_exc = exc
                if attempt < _PERMISSION_ERROR_RETRIES - 1:
                    delay = _PERMISSION_ERROR_BASE_DELAY * (attempt + 1)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Permission denied reading %s (attempt %d/%d), "
                            "retrying in %.3fs: %s",
                            file_path,
                            attempt + 1,
                            _PERMISSION_ERROR_RETRIES,
                            delay,
                            exc,
                        )
                    await asyncio.sleep(delay)
        if last_exc is not None:
            logger.error(
                "Permission denied reading managed OAuth account file %s "
                "after %d retries: %s",
                file_path,
                _PERMISSION_ERROR_RETRIES,
                last_exc,
            )
        return None

    async def load_all_accounts(self) -> list[ManagedOAuthAccount]:
        """Load and validate all account files."""
        await self._ensure_storage_dir()
        files = await asyncio.to_thread(self._iter_account_files_sync)
        loaded: list[ManagedOAuthAccount] = []
        for file_path in files:
            raw = await self._read_file_with_retry(file_path)
            if raw is None:
                continue
            try:
                parsed = json.loads(raw)
                account = ManagedOAuthAccount.model_validate(parsed)
                now_ms = int(time.time() * 1000)
                normalized = account.cleared_if_local_rate_limit_expired(now_ms)
                if normalized.rate_limited_until != account.rate_limited_until:
                    await self.save_account(normalized)
                    account = normalized
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
        raw = await self._read_file_with_retry(path)
        if raw is None:
            return None
        try:
            account = ManagedOAuthAccount.model_validate_json(raw)
        except Exception as exc:
            logger.warning(
                "Skipping invalid managed OAuth account file for %s: %s",
                account_id,
                exc,
                exc_info=True,
            )
            return None
        now_ms = int(time.time() * 1000)
        normalized = account.cleared_if_local_rate_limit_expired(now_ms)
        if normalized.rate_limited_until != account.rate_limited_until:
            await self.save_account(normalized)
            return normalized
        return account

    @staticmethod
    def _atomic_replace_with_retry(
        src: str,
        dst: str,
        *,
        retries: int = _PERMISSION_ERROR_RETRIES,
        base_delay: float = _PERMISSION_ERROR_BASE_DELAY,
    ) -> None:
        last_exc: PermissionError | None = None
        for attempt in range(retries):
            try:
                os.replace(src, dst)
                return
            except PermissionError as exc:
                last_exc = exc
                if attempt < retries - 1:
                    delay = base_delay * (attempt + 1)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Permission denied replacing %s (attempt %d/%d), "
                            "retrying in %.3fs: %s",
                            dst,
                            attempt + 1,
                            retries,
                            delay,
                            exc,
                        )
                    time.sleep(delay)
        raise last_exc  # type: ignore[misc]

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
            self._atomic_replace_with_retry(temp_path, str(path))
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
        return [
            ManagedOAuthAccountSummary.from_account(account) for account in accounts
        ]
