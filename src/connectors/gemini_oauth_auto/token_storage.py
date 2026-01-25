"""
TokenStorageService implementation.

Manages persistence of OAuth credentials for multiple accounts.

Storage location: var/gemini_oauth_accounts/{account_id}.json
Each account is stored as a separate JSON file for easy management.
"""

import asyncio
import contextlib
import json
import logging
import os
import platform
import tempfile
from pathlib import Path

from src.connectors.gemini_oauth_auto.interfaces import ITokenStorage
from src.connectors.gemini_oauth_auto.models import AccountSummary, StoredAccount

logger = logging.getLogger(__name__)


class TokenStorageService(ITokenStorage):
    """Token storage service implementation.

    Manages var/gemini_oauth_accounts/ directory with one JSON file per account.

    Features:
    - Atomic writes via temp file + rename
    - Restrictive file permissions (600 on POSIX)
    - Graceful handling of corrupted files
    - Non-blocking async file operations via asyncio.to_thread
    """

    def __init__(self, storage_path: Path | str | None = None) -> None:
        """Initialize token storage.

        Args:
            storage_path: Path to storage directory.
                          Default: var/gemini_oauth_accounts/
        """
        from src.connectors.gemini_oauth_auto.constants import DEFAULT_STORAGE_PATH

        if storage_path is None:
            self._storage_path = Path(DEFAULT_STORAGE_PATH)
        elif isinstance(storage_path, str):
            self._storage_path = Path(storage_path)
        else:
            self._storage_path = storage_path

    def _get_account_path(self, account_id: str) -> Path:
        """Get file path for account JSON file.

        Args:
            account_id: Account identifier

        Returns:
            Path to {account_id}.json file
        """
        return self._storage_path / f"{account_id}.json"

    def _ensure_directory_exists_sync(self) -> None:
        """Create storage directory if it doesn't exist (sync version)."""
        if not self._storage_path.exists():
            self._storage_path.mkdir(parents=True, exist_ok=True)
            logger.debug("Created storage directory: %s", self._storage_path)

    async def _ensure_directory_exists(self) -> None:
        """Create storage directory if it doesn't exist."""
        await asyncio.to_thread(self._ensure_directory_exists_sync)

    def _read_file_sync(self, file_path: Path) -> str | None:
        """Read file content synchronously."""
        try:
            return file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Error reading file %s: %s", file_path, e)
            return None

    def _write_file_atomic_sync(
        self, file_path: Path, content: str, account_id: str
    ) -> None:
        """Write file atomically using temp file + rename (sync version)."""
        self._ensure_directory_exists_sync()

        # Write to temp file first for atomic operation
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp",
            prefix=f"{account_id}_",
            dir=self._storage_path,
        )

        try:
            # Write content to temp file
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                # If fdopen failed or write failed, ensure fd is closed
                # before we try to unlink (especially important on Windows)
                with contextlib.suppress(OSError):
                    os.close(fd)
                raise

            # Set restrictive permissions on POSIX (before rename for security)
            if platform.system() != "Windows":
                os.chmod(temp_path, 0o600)

            # Atomic rename (within same filesystem)
            # On Windows, we need to remove the target first if it exists
            if platform.system() == "Windows" and file_path.exists():
                file_path.unlink()

            Path(temp_path).rename(file_path)
            logger.debug("Saved account: %s", account_id)

        except Exception:
            # Clean up temp file on error
            with contextlib.suppress(OSError):
                os.unlink(temp_path)
            raise

    async def load_all_accounts(self) -> list[StoredAccount]:
        """Load all accounts from storage directory.

        Returns:
            List of valid accounts. Corrupted files are logged and skipped.
        """
        await self._ensure_directory_exists()

        accounts: list[StoredAccount] = []

        if not self._storage_path.exists():
            return accounts

        # Collect JSON files
        json_files = [
            f
            for f in self._storage_path.iterdir()
            if f.is_file() and f.suffix == ".json"
        ]

        for file_path in json_files:
            try:
                content = await asyncio.to_thread(self._read_file_sync, file_path)
                if content is None:
                    continue

                data = json.loads(content)
                account = StoredAccount.model_validate(data)
                accounts.append(account)
                logger.debug("Loaded account: %s", account.account_id)

            except json.JSONDecodeError as e:
                logger.warning(
                    "Skipping corrupted account file %s: JSON decode error: %s",
                    file_path.name,
                    str(e),
                )
            except Exception as e:
                logger.warning(
                    "Skipping invalid account file %s: %s",
                    file_path.name,
                    str(e),
                )

        logger.debug("Loaded %d accounts from storage", len(accounts))
        return accounts

    async def get_account(self, account_id: str) -> StoredAccount | None:
        """Get specific account by ID.

        Args:
            account_id: Account identifier to retrieve

        Returns:
            StoredAccount if found and valid, None otherwise.
        """
        file_path = self._get_account_path(account_id)

        if not file_path.exists():
            return None

        try:
            content = await asyncio.to_thread(self._read_file_sync, file_path)
            if content is None:
                return None

            data = json.loads(content)
            return StoredAccount.model_validate(data)

        except Exception as e:
            logger.warning(
                "Error reading account %s: %s",
                account_id,
                str(e),
            )
            return None

    async def save_account(self, account: StoredAccount) -> None:
        """Save account credentials atomically.

        Uses temp file + rename pattern for atomic writes.
        Sets restrictive permissions (600) on POSIX systems.

        Args:
            account: Account to save

        Raises:
            IOError: If file cannot be written
        """
        file_path = self._get_account_path(account.account_id)

        # Serialize to JSON with indentation for readability
        json_content = account.model_dump_json(indent=2)

        await asyncio.to_thread(
            self._write_file_atomic_sync, file_path, json_content, account.account_id
        )

    async def delete_account(self, account_id: str) -> bool:
        """Delete account credentials file.

        Args:
            account_id: Account identifier to delete

        Returns:
            True if deleted, False if account not found.
        """
        file_path = self._get_account_path(account_id)

        if not file_path.exists():
            return False

        try:
            await asyncio.to_thread(file_path.unlink)
            logger.info("Deleted account: %s", account_id)
            return True
        except OSError as e:
            logger.error("Failed to delete account %s: %s", account_id, str(e))
            return False

    async def list_accounts(self) -> list[AccountSummary]:
        """List all accounts with status information.

        Returns:
            List of AccountSummary for display purposes.
        """
        accounts = await self.load_all_accounts()
        return [AccountSummary.from_stored_account(acc) for acc in accounts]
