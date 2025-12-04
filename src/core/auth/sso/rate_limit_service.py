"""
Rate limiting service for SSO authentication.

This module provides rate limiting functionality to protect against
brute-force attacks on confirmation codes and authentication endpoints.
"""

from datetime import datetime, timedelta, timezone

import aiosqlite

from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.exceptions import SSOException
from src.core.auth.sso.models import RateLimitResult


class RateLimitService:
    """
    Rate limiting for confirmation code attempts and authentication.

    Implements exponential backoff for repeated failures.
    """

    # Configuration
    BASE_DELAY_SECONDS = 2  # Start with 2 seconds
    MAX_DELAY_SECONDS = 3600  # Cap at 1 hour

    def __init__(self, database_manager: DatabaseManager):
        """
        Initialize rate limit service.

        Args:
            database_manager: Database manager instance
        """
        self.db_manager = database_manager

    async def check_rate_limit(self, identifier: str) -> RateLimitResult:
        """
        Check if identifier is rate limited.

        Args:
            identifier: IP address or session ID to check

        Returns:
            RateLimitResult indicating if allowed and retry time

        Raises:
            SSOException: If database query fails
        """
        try:
            async with aiosqlite.connect(self.db_manager.database_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    """
                    SELECT blocked_until
                    FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                row = await cursor.fetchone()

                if not row or not row["blocked_until"]:
                    return RateLimitResult(allowed=True, retry_after=0)

                blocked_until = datetime.fromisoformat(row["blocked_until"])
                # Assume UTC if no timezone info
                if blocked_until.tzinfo is None:
                    blocked_until = blocked_until.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)

                if blocked_until > now:
                    retry_after = int((blocked_until - now).total_seconds())
                    return RateLimitResult(
                        allowed=False,
                        retry_after=max(1, retry_after),
                    )

                return RateLimitResult(allowed=True, retry_after=0)

        except Exception as e:
            raise SSOException(
                "Failed to check rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def record_failed_attempt(self, identifier: str) -> None:
        """
        Record a failed attempt and update backoff.

        Increments failure count and calculates new blocked_until time
        using exponential backoff.

        Args:
            identifier: IP address or session ID

        Raises:
            SSOException: If database update fails
        """
        try:
            async with aiosqlite.connect(self.db_manager.database_path) as db:
                # Get current state or initialize
                cursor = await db.execute(
                    """
                    SELECT failed_attempts
                    FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                row = await cursor.fetchone()

                if row:
                    failed_attempts = row[0] + 1
                else:
                    failed_attempts = 1

                # Calculate backoff
                # Formula: base * 2^(attempts - 1)
                # Attempt 1: 2 * 2^0 = 2s
                # Attempt 2: 2 * 2^1 = 4s
                # Attempt 3: 2 * 2^2 = 8s
                # ...
                backoff_seconds = self.BASE_DELAY_SECONDS * (2 ** (failed_attempts - 1))
                backoff_seconds = min(backoff_seconds, self.MAX_DELAY_SECONDS)

                blocked_until = datetime.now(timezone.utc) + timedelta(
                    seconds=backoff_seconds
                )

                # Upsert record
                await db.execute(
                    """
                    INSERT INTO rate_limits (
                        identifier, failed_attempts, last_attempt_at, blocked_until
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(identifier) DO UPDATE SET
                        failed_attempts = excluded.failed_attempts,
                        last_attempt_at = excluded.last_attempt_at,
                        blocked_until = excluded.blocked_until
                    """,
                    (
                        identifier,
                        failed_attempts,
                        datetime.now(timezone.utc).isoformat(),
                        blocked_until.isoformat(),
                    ),
                )
                await db.commit()

        except Exception as e:
            raise SSOException(
                "Failed to record failed attempt",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def reset_rate_limit(self, identifier: str) -> None:
        """
        Reset rate limit after successful authorization.

        Args:
            identifier: IP address or session ID

        Raises:
            SSOException: If database update fails
        """
        try:
            async with aiosqlite.connect(self.db_manager.database_path) as db:
                await db.execute(
                    """
                    DELETE FROM rate_limits
                    WHERE identifier = ?
                    """,
                    (identifier,),
                )
                await db.commit()

        except Exception as e:
            raise SSOException(
                "Failed to reset rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e
