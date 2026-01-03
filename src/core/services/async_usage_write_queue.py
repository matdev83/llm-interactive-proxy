"""Async write queue for usage records with background batch processing.

This module provides an async-safe write queue that buffers usage records
and writes them to the database in batches via a background task.
This prevents database operations from blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:

    from src.core.domain.usage_record import UsageRecord

logger = logging.getLogger(__name__)


class IUsageRecordWriter(Protocol):
    """Protocol for usage record batch writers."""

    async def batch_insert(self, records: list[UsageRecord]) -> int:
        """Insert a batch of records.

        Args:
            records: List of records to insert

        Returns:
            Number of records successfully inserted
        """
        ...

    async def batch_update(self, records: list[UsageRecord]) -> int: ...


@dataclass(frozen=True)
class QueueStatistics:
    """Statistics for the async usage write queue."""

    is_running: bool
    insert_queue_size: int
    update_queue_size: int
    pending_count: int
    total_inserts: int
    total_updates: int
    total_batches: int
    last_flush_time: str | None
    batch_size: int
    flush_interval_seconds: float


class AsyncUsageWriteQueue:
    """Async-safe write queue for usage records.

    Buffers usage records and writes them to the database in batches
    via a background asyncio task. This ensures database operations
    never block the event loop handling requests.

    Features:
    - Non-blocking record submission via queue.put_nowait()
    - Configurable batch size and flush interval
    - Graceful shutdown with drain
    - Separate queues for inserts and updates
    - In-memory cache for pending records (to support fast lookups)

    Attributes:
        _insert_queue: Queue for new records to insert
        _update_queue: Queue for existing records to update
        _writer: Backend writer (repository) for database operations
        _batch_size: Maximum batch size before flush
        _flush_interval: Seconds between automatic flushes
        _background_task: Background flush task
        _shutdown_event: Event to signal shutdown
        _pending_records: In-memory cache of pending records (not yet persisted)
    """

    def __init__(
        self,
        writer: IUsageRecordWriter,
        batch_size: int = 100,
        flush_interval_seconds: float = 5.0,
        max_queue_size: int = 10000,
        max_pending_records: int | None = None,
    ):
        """Initialize the async write queue.

        Args:
            writer: Backend writer for database operations
            batch_size: Maximum batch size before flush (default: 100)
            flush_interval_seconds: Seconds between automatic flushes (default: 5.0)
            max_queue_size: Maximum queue size before blocking (default: 10000)
            max_pending_records: Maximum pending records cache size (default: max_queue_size * 2)
        """
        self._writer = writer
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._max_queue_size = max_queue_size
        # Limit pending records cache to prevent unbounded memory growth
        # Use 2x queue size to allow for some buffer while processing
        self._max_pending_records = (
            max_pending_records
            if max_pending_records is not None
            else max_queue_size * 2
        )

        # Async queues for records
        self._insert_queue: asyncio.Queue[UsageRecord] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._update_queue: asyncio.Queue[UsageRecord] = asyncio.Queue(
            maxsize=max_queue_size
        )

        # In-memory cache for pending records (fast lookups before persistence)
        # Dict maintains insertion order (Python 3.7+) for FIFO eviction
        self._pending_records: dict[str, UsageRecord] = {}
        self._pending_lock = asyncio.Lock()

        # Background task control
        self._background_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._is_running = False

        # Statistics - use lock for concurrent access
        self._total_inserts = 0
        self._total_updates = 0
        self._total_batches = 0
        self._last_flush_time: datetime | None = None
        self._stats_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background flush task."""
        if self._is_running:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("AsyncUsageWriteQueue already running")
            return

        self._shutdown_event.clear()
        self._is_running = True
        self._background_task = asyncio.create_task(
            self._flush_loop(), name="usage_write_queue_flush"
        )
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Started AsyncUsageWriteQueue (batch_size=%d, flush_interval=%.1fs)",
                self._batch_size,
                self._flush_interval,
            )

    async def stop(self, timeout: float = 10.0) -> None:
        """Stop the background task and drain remaining records.

        Args:
            timeout: Maximum time to wait for drain (default: 10.0 seconds)
        """
        if not self._is_running:
            return

        if logger.isEnabledFor(logging.INFO):
            logger.info("Stopping AsyncUsageWriteQueue...")
        self._shutdown_event.set()

        if self._background_task:
            try:
                await asyncio.wait_for(self._background_task, timeout=timeout)
            except asyncio.TimeoutError:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "AsyncUsageWriteQueue shutdown timed out, cancelling",
                        exc_info=True,
                    )
                self._background_task.cancel()
                import contextlib

                with contextlib.suppress(asyncio.CancelledError):
                    await self._background_task

        # Final drain
        await self._drain_queues()

        self._is_running = False
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "AsyncUsageWriteQueue stopped (total_inserts=%d, total_updates=%d, total_batches=%d)",
                self._total_inserts,
                self._total_updates,
                self._total_batches,
            )

    def enqueue_insert(self, record: UsageRecord) -> bool:
        """Enqueue a record for insertion (non-blocking).

        Args:
            record: Usage record to insert

        Returns:
            True if enqueued, False if queue is full
        """
        try:
            self._insert_queue.put_nowait(record)
            # Add to pending cache for fast lookups (sync since we're in non-async context)
            # Enforce size limit to prevent unbounded memory growth
            self._enforce_pending_records_limit()
            self._pending_records[record.id] = record
            return True
        except asyncio.QueueFull:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Insert queue full, dropping record %s (queue_size=%d)",
                    record.id,
                    self._max_queue_size,
                    exc_info=True,
                )
            return False

    def enqueue_update(self, record: UsageRecord) -> bool:
        """Enqueue a record for update (non-blocking).

        Args:
            record: Usage record to update

        Returns:
            True if enqueued, False if queue is full
        """
        try:
            self._update_queue.put_nowait(record)
            # Update pending cache (sync since we're in non-async context)
            # Enforce size limit to prevent unbounded memory growth
            self._enforce_pending_records_limit()
            self._pending_records[record.id] = record
            return True
        except asyncio.QueueFull:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Update queue full, dropping record %s (queue_size=%d)",
                    record.id,
                    self._max_queue_size,
                    exc_info=True,
                )
            return False

    async def get_pending_record(self, record_id: str) -> UsageRecord | None:
        """Get a pending record from the cache.

        This allows fast lookups for records that haven't been persisted yet.

        Args:
            record_id: ID of the record to retrieve

        Returns:
            UsageRecord if found in pending cache, None otherwise
        """
        async with self._pending_lock:
            return self._pending_records.get(record_id)

    async def _add_to_pending(self, record: UsageRecord) -> None:
        """Add a record to the pending cache."""
        async with self._pending_lock:
            self._pending_records[record.id] = record

    def _enforce_pending_records_limit(self) -> None:
        """Enforce size limit on pending records cache using FIFO eviction.

        This prevents unbounded memory growth when records accumulate faster
        than they can be processed, or when the background task stops/fails.
        """
        # Dict maintains insertion order (Python 3.7+), so we can evict oldest entries
        while len(self._pending_records) >= self._max_pending_records:
            # Remove oldest entry (first inserted)
            oldest_id = next(iter(self._pending_records))
            self._pending_records.pop(oldest_id, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Evicted oldest pending record %s (max_pending_records=%d reached)",
                    oldest_id,
                    self._max_pending_records,
                )

    async def _remove_from_pending(self, record_ids: list[str]) -> None:
        """Remove records from the pending cache."""
        async with self._pending_lock:
            for record_id in record_ids:
                self._pending_records.pop(record_id, None)

    async def _flush_loop(self) -> None:
        """Background loop for periodic flushing."""
        while not self._shutdown_event.is_set():
            try:
                # Wait for flush interval or shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self._flush_interval,
                    )
                    # Shutdown signaled
                    break
                except asyncio.TimeoutError:
                    # Timeout - time to flush
                    pass

                await self._flush_batches()

            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("Error in flush loop: %s", e, exc_info=True)
                # Continue loop despite errors
                await asyncio.sleep(1.0)

    async def _flush_batches(self) -> None:
        """Flush batches from both queues."""
        # Collect insert batch
        insert_batch = await self._collect_batch(self._insert_queue)
        if insert_batch:
            await self._process_insert_batch(insert_batch)

        # Collect update batch
        update_batch = await self._collect_batch(self._update_queue)
        if update_batch:
            await self._process_update_batch(update_batch)

        if insert_batch or update_batch:
            async with self._stats_lock:
                self._last_flush_time = datetime.now(timezone.utc)
                self._total_batches += 1

    async def _collect_batch(
        self, queue: asyncio.Queue[UsageRecord]
    ) -> list[UsageRecord]:
        """Collect up to batch_size records from a queue.

        Args:
            queue: Queue to collect from

        Returns:
            List of records (up to batch_size)
        """
        batch: list[UsageRecord] = []

        while len(batch) < self._batch_size:
            try:
                record = queue.get_nowait()
                batch.append(record)
            except asyncio.QueueEmpty:
                break

        return batch

    async def _process_insert_batch(self, batch: list[UsageRecord]) -> None:
        """Process a batch of inserts.

        Args:
            batch: List of records to insert
        """
        if not batch:
            return

        # Collect record IDs before processing to ensure cleanup even on failure
        record_ids = [r.id for r in batch]

        try:
            count = await self._writer.batch_insert(batch)
            async with self._stats_lock:
                self._total_inserts += count

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Inserted %d usage records", count)

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Failed to insert batch of %d records: %s", len(batch), e, exc_info=True)
            # Records are lost - could implement retry queue here

        finally:
            # Always remove from pending cache to prevent memory leak
            # Records have been removed from queue, so they won't be retried
            await self._remove_from_pending(record_ids)

    async def _process_update_batch(self, batch: list[UsageRecord]) -> None:
        """Process a batch of updates.

        Args:
            batch: List of records to update
        """
        if not batch:
            return

        # Collect record IDs before processing to ensure cleanup even on failure
        record_ids = [r.id for r in batch]

        try:
            count = await self._writer.batch_update(batch)
            async with self._stats_lock:
                self._total_updates += count

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Updated %d usage records", count)

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error("Failed to update batch of %d records: %s", len(batch), e, exc_info=True)
            # Records are lost - could implement retry queue here

        finally:
            # Always remove from pending cache to prevent memory leak
            # Records have been removed from queue, so they won't be retried
            await self._remove_from_pending(record_ids)

    async def _drain_queues(self) -> None:
        """Drain all remaining records from queues."""
        while not self._insert_queue.empty() or not self._update_queue.empty():
            await self._flush_batches()

    @property
    def insert_queue_size(self) -> int:
        """Get current insert queue size."""
        return self._insert_queue.qsize()

    @property
    def update_queue_size(self) -> int:
        """Get current update queue size."""
        return self._update_queue.qsize()

    @property
    def pending_count(self) -> int:
        """Get count of pending records in cache."""
        return len(self._pending_records)

    @property
    def statistics(self) -> QueueStatistics:
        """Get queue statistics."""
        return QueueStatistics(
            is_running=self._is_running,
            insert_queue_size=self.insert_queue_size,
            update_queue_size=self.update_queue_size,
            pending_count=self.pending_count,
            total_inserts=self._total_inserts,
            total_updates=self._total_updates,
            total_batches=self._total_batches,
            last_flush_time=(
                self._last_flush_time.isoformat() if self._last_flush_time else None
            ),
            batch_size=self._batch_size,
            flush_interval_seconds=self._flush_interval,
        )
