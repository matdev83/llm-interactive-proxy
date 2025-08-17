"""
Synchronous session manager wrapper for test compatibility.

This provides a synchronous interface to the async SessionService for legacy test code.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.session import Session
    from src.core.interfaces.session_service import ISessionService


class SyncSessionManager:
    """Synchronous wrapper around async SessionService for test compatibility."""

    def __init__(self, session_service: ISessionService) -> None:
        """Initialize the sync session manager.

        Args:
            session_service: The async session service to wrap
        """
        self._session_service = session_service

    def get_session(self, session_id: str) -> Session:
        """Get a session synchronously.

        Args:
            session_id: The session ID

        Returns:
            The session object
        """
        # Run the async method in the current event loop or create a new one
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, create a task
                import concurrent.futures

                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    try:
                        return new_loop.run_until_complete(
                            self._session_service.get_session(session_id)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    return future.result()
            else:
                return loop.run_until_complete(
                    self._session_service.get_session(session_id)
                )
        except RuntimeError:
            # Create a new event loop for this operation
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._session_service.get_session(session_id)
                )
            finally:
                loop.close()

    async def get_session_async(self, session_id: str) -> Session:
        """Get a session asynchronously (for async test contexts).

        Args:
            session_id: The session ID

        Returns:
            The session object
        """
        return await self._session_service.get_session(session_id)

    def create_session(self, session_id: str) -> Session:
        """Create a session synchronously.

        Args:
            session_id: The session ID

        Returns:
            The created session object
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("Cannot call sync method from async context")
            else:
                return loop.run_until_complete(
                    self._session_service.create_session(session_id)
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._session_service.create_session(session_id)
                )
            finally:
                loop.close()

    def get_or_create_session(self, session_id: str) -> Session:
        """Get or create a session synchronously.

        Args:
            session_id: The session ID

        Returns:
            The session object
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("Cannot call sync method from async context")
            else:
                return loop.run_until_complete(
                    self._session_service.get_or_create_session(session_id)
                )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._session_service.get_or_create_session(session_id)
                )
            finally:
                loop.close()

    def update_session(self, session: Session) -> None:
        """Update a session synchronously.

        Args:
            session: The session to update
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("Cannot call sync method from async context")
            else:
                loop.run_until_complete(self._session_service.update_session(session))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._session_service.update_session(session))
            finally:
                loop.close()
