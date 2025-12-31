"""SQLModel repositories for SSO authentication."""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import sqlalchemy
import sqlalchemy.exc
from sqlmodel import select

from src.core.auth.sso.exceptions import SSOException
from src.core.auth.sso.models import RateLimitResult, TokenRecord
from src.core.database.models.sso import (
    AgentTokenTable,
    PendingAuthorizationTable,
    RateLimitTable,
    SSOLoginTokenTable,
)
from src.core.database.repositories.base import AsyncRepository

if TYPE_CHECKING:
    from src.core.database.engine import DatabaseEngine

logger = logging.getLogger(__name__)


class SQLModelTokenRepository(AsyncRepository[AgentTokenTable]):
    """SQLModel-based repository for agent token storage."""

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize token repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)

    @property
    def model_class(self) -> type[AgentTokenTable]:
        """Return the SQLModel class this repository manages."""
        return AgentTokenTable

    async def store_token(self, token_record: TokenRecord) -> None:
        """Store a new token record.

        Args:
            token_record: Token record to store

        Raises:
            SSOException: If storage fails
        """
        try:
            table_record = AgentTokenTable(
                id=token_record.id,
                token_hash=token_record.token_hash,
                user_id=token_record.user_id,
                user_email=token_record.user_email,
                provider=token_record.provider,
                is_authenticated=token_record.is_authenticated,
                is_active=token_record.is_active,
                created_at=token_record.created_at,
                last_authenticated_at=token_record.last_authenticated_at,
                auth_expires_at=token_record.auth_expires_at,
            )
            await self.create(table_record)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to store token record",
                details={"token_id": token_record.id, "error": str(e)},
                original_error=e,
            ) from e

    async def get_token_by_id(self, token_id: str) -> TokenRecord | None:
        """Get token record by ID.

        Args:
            token_id: Token ID

        Returns:
            TokenRecord if found, None otherwise
        """
        try:
            async with self._engine.session() as session:
                result = await session.get(AgentTokenTable, token_id)
                if result is None:
                    return None
                return self._table_to_record(result)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to get token by ID",
                details={"token_id": token_id, "error": str(e)},
                original_error=e,
            ) from e

    async def find_by_user_id(self, user_id: str) -> TokenRecord | None:
        """Find an active token record by user ID.

        Args:
            user_id: User ID to search for

        Returns:
            TokenRecord if found, None otherwise

        Raises:
            SSOException: If database query fails
        """
        try:
            async with self._engine.session() as session:
                statement = (
                    select(AgentTokenTable)
                    .where(
                        AgentTokenTable.user_id == user_id,
                        AgentTokenTable.is_active == True,
                    )
                    .order_by(AgentTokenTable.created_at.desc())  # type: ignore[attr-defined]
                    .limit(1)
                )
                result = await session.execute(statement)
                row = result.scalar_one_or_none()

                if row is None:
                    return None
                return self._table_to_record(row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to find token by user ID",
                details={"user_id": user_id, "error": str(e)},
                original_error=e,
            ) from e

    async def find_by_hash(self, token_hash: str) -> TokenRecord | None:
        """Find token record by hash using constant-time comparison.

        Args:
            token_hash: Token hash to search for

        Returns:
            TokenRecord if found, None otherwise

        Raises:
            SSOException: If database query fails
        """
        try:
            async with self._engine.session() as session:
                statement = select(AgentTokenTable).where(
                    AgentTokenTable.is_active == True
                )
                result = await session.execute(statement)
                rows = result.scalars().all()

                # Perform constant-time comparison
                matching_row = None
                for row in rows:
                    try:
                        if hmac.compare_digest(str(row.token_hash), str(token_hash)):
                            matching_row = row
                            # Continue iterating to maintain constant time
                    except (TypeError, ValueError):
                        continue

                if matching_row is None:
                    return None
                return self._table_to_record(matching_row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to find token by hash",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def update_auth_status(
        self,
        token_id: str,
        authenticated: bool,
        expiry: datetime | None,
    ) -> None:
        """Update authentication status for a token.

        Args:
            token_id: Token ID to update
            authenticated: New authentication status
            expiry: New expiry timestamp (None to clear)

        Raises:
            SSOException: If update fails
        """
        try:
            async with self._engine.session() as session:
                row = await session.get(AgentTokenTable, token_id)
                if row:
                    row.is_authenticated = authenticated
                    row.last_authenticated_at = datetime.now(timezone.utc)
                    row.auth_expires_at = expiry
                    session.add(row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to update authentication status",
                details={"token_id": token_id, "error": str(e)},
                original_error=e,
            ) from e

    async def revoke_token(self, token_id: str) -> None:
        """Mark token as revoked (soft delete).

        Args:
            token_id: Token ID to revoke

        Raises:
            SSOException: If revocation fails
        """
        try:
            async with self._engine.session() as session:
                row = await session.get(AgentTokenTable, token_id)
                if row:
                    row.is_active = False
                    session.add(row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to revoke token",
                details={"token_id": token_id, "error": str(e)},
                original_error=e,
            ) from e

    async def get_all_token_hashes(self) -> list[str]:
        """Get all active token hashes for verification.

        Returns:
            List of active token hashes

        Raises:
            SSOException: If query fails
        """
        try:
            async with self._engine.session() as session:
                statement = select(AgentTokenTable.token_hash).where(
                    AgentTokenTable.is_active == True
                )
                result = await session.execute(statement)
                return [row[0] for row in result.all()]
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to get token hashes",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def create_login_token(
        self, ttl_minutes: int = 10, agent_token_id: str | None = None
    ) -> str:
        """Create a one-off login token for SSO link validation.

        Args:
            ttl_minutes: Token validity duration in minutes
            agent_token_id: Optional existing agent token ID for re-authentication

        Returns:
            Generated token string

        Raises:
            SSOException: If creation fails
        """
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl_minutes)

        try:
            table_record = SSOLoginTokenTable(
                token=token,
                created_at=now,
                expires_at=expires_at,
                agent_token_id=agent_token_id,
            )
            async with self._engine.session() as session:
                session.add(table_record)
            return token
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to create login token",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def verify_and_consume_login_token(
        self, token: str
    ) -> tuple[bool, str | None]:
        """Verify and consume (delete) a login token.

        Args:
            token: The token to verify

        Returns:
            Tuple of (is_valid, agent_token_id)
        """
        if not token:
            return (False, None)

        try:
            async with self._engine.session() as session:
                row = await session.get(SSOLoginTokenTable, token)

                if not row:
                    return (False, None)

                expires_at = row.expires_at
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if datetime.now(timezone.utc) > expires_at:
                    # Delete expired token
                    await session.delete(row)
                    return (False, None)

                # Token is valid, consume it
                agent_token_id = row.agent_token_id
                await session.delete(row)
                return (True, agent_token_id)
        except (
            sqlalchemy.exc.SQLAlchemyError,
            ValueError,
            AttributeError,
            TypeError,
        ) as e:
            logger.error(
                "Failed to verify/consume login token: %s",
                e,
                exc_info=True,
                extra={"token_length": len(token) if token else 0},
            )
            return (False, None)

    def _table_to_record(self, row: AgentTokenTable) -> TokenRecord:
        """Convert database row to TokenRecord."""
        return TokenRecord(
            id=row.id,
            token_hash=row.token_hash,
            user_id=row.user_id,
            user_email=row.user_email,
            provider=row.provider,
            is_authenticated=row.is_authenticated,
            is_active=row.is_active,
            created_at=row.created_at,
            last_authenticated_at=row.last_authenticated_at,
            auth_expires_at=row.auth_expires_at,
        )


class SQLModelRateLimitRepository(AsyncRepository[RateLimitTable]):
    """SQLModel-based repository for rate limiting."""

    # Configuration
    BASE_DELAY_SECONDS = 2  # Start with 2 seconds
    MAX_DELAY_SECONDS = 3600  # Cap at 1 hour

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize rate limit repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)

    @property
    def model_class(self) -> type[RateLimitTable]:
        """Return the SQLModel class this repository manages."""
        return RateLimitTable

    async def check_rate_limit(self, identifier: str) -> RateLimitResult:
        """Check if identifier is rate limited.

        Args:
            identifier: IP address or session ID to check

        Returns:
            RateLimitResult indicating if allowed and retry time

        Raises:
            SSOException: If database query fails
        """
        try:
            async with self._engine.session() as session:
                row = await session.get(RateLimitTable, identifier)

                if not row or not row.blocked_until:
                    return RateLimitResult(allowed=True, retry_after=0)

                blocked_until = row.blocked_until
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
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to check rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def record_failed_attempt(self, identifier: str) -> None:
        """Record a failed attempt and update backoff.

        Args:
            identifier: IP address or session ID

        Raises:
            SSOException: If database update fails
        """
        try:
            async with self._engine.session() as session:
                row = await session.get(RateLimitTable, identifier)

                if row:
                    failed_attempts = row.failed_attempts + 1
                else:
                    failed_attempts = 1
                    row = RateLimitTable(identifier=identifier)

                # Calculate backoff: base * 2^(attempts - 1)
                backoff_seconds = self.BASE_DELAY_SECONDS * (2 ** (failed_attempts - 1))
                backoff_seconds = min(backoff_seconds, self.MAX_DELAY_SECONDS)

                blocked_until = datetime.now(timezone.utc) + timedelta(
                    seconds=backoff_seconds
                )

                row.failed_attempts = failed_attempts
                row.last_attempt_at = datetime.now(timezone.utc)
                row.blocked_until = blocked_until
                session.add(row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to record failed attempt",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e

    async def reset_rate_limit(self, identifier: str) -> None:
        """Reset rate limit after successful authorization.

        Args:
            identifier: IP address or session ID

        Raises:
            SSOException: If database update fails
        """
        try:
            async with self._engine.session() as session:
                row = await session.get(RateLimitTable, identifier)
                if row:
                    await session.delete(row)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to reset rate limit",
                details={"identifier": identifier, "error": str(e)},
                original_error=e,
            ) from e


class SQLModelAuthorizationRepository(AsyncRepository[PendingAuthorizationTable]):
    """SQLModel-based repository for pending authorizations."""

    def __init__(self, engine: DatabaseEngine) -> None:
        """Initialize authorization repository.

        Args:
            engine: Database engine for session creation
        """
        super().__init__(engine)

    @property
    def model_class(self) -> type[PendingAuthorizationTable]:
        """Return the SQLModel class this repository manages."""
        return PendingAuthorizationTable

    async def create_pending(
        self,
        id: str,
        sso_state: str,
        user_email: str,
        user_id: str,
        provider: str,
        confirmation_code_hash: str,
        max_attempts: int,
        expiry_minutes: int,
        client_ip: str,
    ) -> None:
        """Create a pending authorization request.

        Args:
            id: Unique ID for the record
            sso_state: OAuth2 state parameter
            user_email: User's email
            user_id: User's unique ID
            provider: Identity provider
            confirmation_code_hash: Hashed confirmation code
            max_attempts: Maximum verification attempts
            expiry_minutes: Minutes until expiry
            client_ip: Client IP address

        Raises:
            SSOException: If creation fails
        """
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

        try:
            table_record = PendingAuthorizationTable(
                id=id,
                sso_state=sso_state,
                user_email=user_email,
                user_id=user_id,
                provider=provider,
                confirmation_code_hash=confirmation_code_hash,
                attempts_remaining=max_attempts,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
                client_ip=client_ip,
            )
            async with self._engine.session() as session:
                session.add(table_record)
        except sqlalchemy.exc.SQLAlchemyError as e:
            raise SSOException(
                "Failed to create pending authorization",
                details={"error": str(e)},
                original_error=e,
            ) from e

    async def get_by_sso_state(
        self, sso_state: str
    ) -> PendingAuthorizationTable | None:
        """Get pending authorization by SSO state.

        Args:
            sso_state: OAuth2 state parameter

        Returns:
            PendingAuthorizationTable if found, None otherwise
        """
        async with self._engine.session() as session:
            statement = select(PendingAuthorizationTable).where(
                PendingAuthorizationTable.sso_state == sso_state
            )
            result = await session.execute(statement)
            return result.scalar_one_or_none()

    async def delete_by_sso_state(self, sso_state: str) -> None:
        """Delete pending authorization by SSO state.

        Args:
            sso_state: OAuth2 state parameter
        """
        async with self._engine.session() as session:
            statement = select(PendingAuthorizationTable).where(
                PendingAuthorizationTable.sso_state == sso_state
            )
            result = await session.execute(statement)
            row = result.scalar_one_or_none()
            if row:
                await session.delete(row)

    async def decrement_attempts(self, sso_state: str) -> int:
        """Decrement attempts remaining for a pending authorization.

        Args:
            sso_state: OAuth2 state parameter

        Returns:
            New attempts remaining count
        """
        async with self._engine.session() as session:
            statement = select(PendingAuthorizationTable).where(
                PendingAuthorizationTable.sso_state == sso_state
            )
            result = await session.execute(statement)
            row = result.scalar_one_or_none()
            if row:
                row.attempts_remaining = max(0, row.attempts_remaining - 1)
                session.add(row)
                return row.attempts_remaining
            return 0
