"""Validation HTTP client manager for managing HTTP client lifecycle during validation.

This module provides ValidationHttpClientManager which encapsulates validation-time
httpx.AsyncClient creation, tracks the client and cleanup tasks, and ensures
reliable cleanup without leaks.

Feature: backend-stage-solid-refactoring
Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 12.3
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ValidationHttpClientManager:
    """Manages HTTP client lifecycle during validation.

    Encapsulates validation-time httpx.AsyncClient creation (HTTP/2-first with fallback),
    tracks the client and any cleanup tasks, and can reliably clean up without leaks.
    """

    def __init__(self) -> None:
        """Initialize the validation HTTP client manager."""
        self._client: httpx.AsyncClient | None = None
        # Use regular set instead of WeakSet to prevent premature garbage collection
        # before tasks complete, which could lead to HTTP client leaks
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._cleanup_tasks_lock = threading.Lock()

    def get_or_create_client(self) -> httpx.AsyncClient:
        """Get or create a managed HTTP client instance.

        Attempts to create an HTTP/2 client first, falling back to HTTP/1.1
        if HTTP/2 creation fails. Reuses existing client if available and not closed.

        Returns:
            An AsyncClient instance that is tracked for cleanup.

        Raises:
            Exception: If client creation fails after all fallback attempts.
        """
        # Return existing client if available and not closed
        if self._client is not None and not self._client.is_closed:
            return self._client

        client: httpx.AsyncClient | None = None
        try:
            try:
                # Attempt HTTP/2 client creation first
                client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except (
                ValueError,
                RuntimeError,
                OSError,
                ImportError,
                httpx.UnsupportedProtocol,
            ) as e:
                # Fallback to HTTP/1.1 if HTTP/2 setup fails
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "HTTP/2 client creation failed, falling back to HTTP/1.1: %s",
                        e,
                        exc_info=True,
                    )
                client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

            # Track client immediately after creation to ensure cleanup even if
            # exception occurs during subsequent operations
            self._client = client
            return client

        except Exception:
            # If exception occurs after client instantiation (e.g., during an
            # internal post-create step), ensure the created client is immediately
            # closed to prevent resource leaks
            if client is not None and self._client is None:
                # Client was created but not assigned - clean it up immediately
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Schedule cleanup task and track it to prevent resource leaks
                        cleanup_task = asyncio.create_task(client.aclose())
                        with self._cleanup_tasks_lock:
                            self._cleanup_tasks.add(cleanup_task)
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Scheduled cleanup task for client created but not assigned"
                            )
                    else:
                        # No running loop - close synchronously
                        loop.run_until_complete(client.aclose())
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Closed client synchronously (no running event loop)"
                            )
                except (RuntimeError, AttributeError):
                    # No event loop available - client will be cleaned up by finalizer
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "No event loop available for immediate client cleanup"
                        )
            raise

    async def cleanup(self) -> None:
        """Clean up managed HTTP client resources.

        Closes the client if it exists and awaits/cancels any pending cleanup tasks
        with a 5 second timeout. Always clears task references after completion.
        This method is idempotent and fail-safe (should not raise on cleanup errors).
        """
        # Close managed client if exists and not already closed
        if self._client is not None:
            client = self._client
            self._client = None
            try:
                if not client.is_closed:
                    await client.aclose()
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Closed managed HTTP client")
                else:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("Skipped closing already-closed HTTP client")
            except Exception as e:
                # Fail-safe: log but don't raise
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error closing managed HTTP client: %s", e, exc_info=True
                    )

        # Wait for any pending cleanup tasks to complete
        # Ensure all tasks are properly awaited/cancelled even if cleanup fails
        with self._cleanup_tasks_lock:
            pending_tasks = [t for t in self._cleanup_tasks if not t.done()]

        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=5.0,
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        f"Completed {len(pending_tasks)} cleanup task(s) within timeout"
                    )
            except asyncio.TimeoutError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Timeout waiting for cleanup tasks, cancelling remaining tasks"
                    )
                # Cancel all pending tasks
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                # Await cancelled tasks to ensure they complete
                # This prevents task references from preventing garbage collection
                try:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Error awaiting cancelled cleanup tasks: %s",
                            e,
                            exc_info=True,
                        )
            except Exception as e:
                # If gather itself fails, still cancel and await tasks
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Error during cleanup task gather: %s", e, exc_info=True
                    )
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(*pending_tasks, return_exceptions=True)

        # Clear the cleanup tasks set to prevent memory leaks
        # This ensures task references don't prevent garbage collection
        with self._cleanup_tasks_lock:
            self._cleanup_tasks.clear()
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Cleared cleanup task references")

    async def dispose(self) -> None:
        """Dispose of the manager and clean up resources.

        This method is called by DI container disposal and delegates to cleanup().
        It is idempotent and can be called multiple times safely.

        This method ensures that ValidationHttpClientManager resources are properly
        cleaned up when the ServiceProvider is disposed, preventing resource leaks.
        """
        await self.cleanup()
