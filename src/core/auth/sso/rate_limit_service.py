"""
Rate limiting service for SSO authentication.

This module provides rate limiting functionality to prevent brute-force
attacks on confirmation codes and other authentication mechanisms.
"""

from datetime import datetime, timedelta

import aiosqlite

from src.core.auth.sso.exceptions import SSOException
from src.core.auth.sso.models import RateLimitRecord, RateLimitResult


class RateLimitService:
    """Rate limiting for confirmation code attempts."""

    # Exponential backoff configuration
    BASE_BACKOFF_SECONDS = 2  # Base backoff time (2^1 = 2 seconds)
    MAX_BACKOFF_SECONDS = 3600  # Maximum backoff time (1 hour)

    def __init__(self, database_path: str):
        """
        Initialize rate limit service.

        Args:
            database_path: Path to SQLite database file
        """
        self.database_path = database_path

    async def check_rate_limit(self, identifier: str) -> RateLimitResult:
        """
        Check if identifier is rate limited.

        Args:
            identifier: IP address or session ID to check

        Returns:
            RateLimitResult with allowed status and retry_after time

        Raises:
            SSOException: If database query fails
        """
        try:
            async with aiosqlite.connect(self.database_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT identifier, failed_attempts, last_attempt_at, blocked_until
                    FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                row = await cursor.fetchone()

                if row is None:
                    # No rate limit record exists, allow request
                    return RateLimitResult(allowed=True, retry_after=0)

                record = self._row_to_rate_limit_record(row)

                # Check if currently blocked
                if record.blocked_until is not None:
                    now = datetime.utcnow()
                    if now < record.blocked_until:
                        # Still blocked, calculate retry_after
                        retry_after = int((record.blocked_until - now).total_seconds())
                        return RateLimitResult(allowed=False, retry_after=retry_after)

                # Not blocked or block expired
                return RateLimitResult(allowed=True, retry_after=0)

        except aiosqlite.Error as e:
            raise SSOException(
                "Failed to check rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def record_failed_attempt(self, identifier: str) -> None:
        """
        Record a failed attempt and update backoff.

        Implements exponential backoff: 2^N seconds where N is the number
        of consecutive failures, capped at MAX_BACKOFF_SECONDS.

        Args:
            identifier: IP address or session ID

        Raises:
            SSOException: If database update fails
        """
        try:
            async with aiosqlite.connect(self.database_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT identifier, failed_attempts, last_attempt_at, blocked_until
                    FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                row = await cursor.fetchone()

                now = datetime.utcnow()

                if row is None:
                    # First failed attempt
                    failed_attempts = 1
                else:
                    # Increment failed attempts
                    failed_attempts = row["failed_attempts"] + 1

                # Calculate exponential backoff: 2^N seconds
                backoff_seconds = min(
                    self.BASE_BACKOFF_SECONDS**failed_attempts,
                    self.MAX_BACKOFF_SECONDS,
                )
                blocked_until = now + timedelta(seconds=backoff_seconds)

                # Upsert rate limit record
                await db.execute(
                    """
                    INSERT INTO rate_limits (identifier, failed_attempts, last_attempt_at, blocked_until)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(identifier) DO UPDATE SET
                        failed_attempts = excluded.failed_attempts,
                        last_attempt_at = excluded.last_attempt_at,
                        blocked_until = excluded.blocked_until
                    """,
                    (
                        identifier,
                        failed_attempts,
                        now.isoformat(),
                        blocked_until.isoformat(),
                    ),
                )
                await db.commit()

        except aiosqlite.Error as e:
            raise SSOException(
                "Failed to record failed attempt",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def reset_rate_limit(self, identifier: str) -> None:
        """
        Reset rate limit after successful authorization.

        Args:
            identifier: IP address or session ID to reset

        Raises:
            SSOException: If database update fails
        """
        try:
            async with aiosqlite.connect(self.database_path) as db:
                await db.execute(
                    """
                    DELETE FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                await db.commit()
        except aiosqlite.Error as e:
            raise SSOException(
                "Failed to reset rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    def _row_to_rate_limit_record(self, row: aiosqlite.Row) -> RateLimitRecord:
        """
        Convert database row to RateLimitRecord.

        Args:
            row: Database row

        Returns:
            RateLimitRecord instance
        """
        return RateLimitRecord(
            identifier=row["identifier"],
            failed_attempts=row["failed_attempts"],
            last_attempt_at=datetime.fromisoformat(row["last_attempt_at"]),
            blocked_until=(
                datetime.fromisoformat(row["blocked_until"])
                if row["blocked_until"]
                else None
            ),
        )
