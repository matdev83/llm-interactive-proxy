"""Thread-safe in-memory storage for usage records with periodic persistence.

This module provides the InMemoryUsageStore class which maintains usage records
in memory with thread-safe access and periodic persistence to disk.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from src.core.domain.statistics_filter import StatisticsFilter
from src.core.domain.usage_record import UsageRecord

logger = logging.getLogger(__name__)


class InMemoryUsageStore:
    """Thread-safe in-memory storage with periodic disk persistence.

    Uses threading.RLock for concurrent access safety.
    Persists to disk at configurable intervals when dirty.

    Attributes:
        _lock: Reentrant lock for thread-safe access
        _records: Dictionary mapping record IDs to UsageRecord instances
        _dirty: Flag indicating if data has been modified since last flush
        _persistence_path: Path to persistence file
        _flush_interval: Interval in seconds between automatic flushes
        _flush_thread: Background thread for periodic persistence
        _shutdown_event: Event to signal shutdown to background thread
        _max_records: Maximum number of records to keep in memory
    """

    def __init__(
        self,
        persistence_path: Path,
        flush_interval_seconds: float = 30.0,
        max_records_in_memory: int = 100000,
    ):
        """Initialize the in-memory usage store.

        Args:
            persistence_path: Path to the persistence file
            flush_interval_seconds: Interval between automatic flushes
            max_records_in_memory: Maximum records to keep in memory
        """
        self._lock = threading.RLock()
        self._records: dict[str, UsageRecord] = {}
        self._dirty: bool = False
        self._persistence_path = persistence_path
        self._flush_interval = flush_interval_seconds
        self._flush_thread: threading.Thread | None = None
        self._shutdown_event = threading.Event()
        self._max_records = max_records_in_memory

        # Ensure parent directory exists
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)

    def add_record(self, record: UsageRecord) -> None:
        """Add a usage record to the store (thread-safe).

        Args:
            record: Usage record to add
        """
        with self._lock:
            # Enforce max records limit (FIFO eviction)
            while len(self._records) >= self._max_records and self._records:
                # Remove oldest inserted item
                oldest_id = next(iter(self._records))
                del self._records[oldest_id]

            if len(self._records) < self._max_records:
                self._records[record.id] = record
                self._dirty = True

    def get_records(self, filters: StatisticsFilter | None = None) -> list[UsageRecord]:
        """Get usage records matching the filter (thread-safe).

        Args:
            filters: Optional filter to apply. If None, returns all records.

        Returns:
            List of usage records matching the filter
        """
        with self._lock:
            if filters is None:
                return list(self._records.values())
            return [r for r in self._records.values() if filters.matches(r)]

    def update_record(self, record: UsageRecord) -> None:
        """Update an existing usage record (thread-safe).

        Args:
            record: Usage record to update

        Raises:
            KeyError: If record with given ID does not exist
        """
        with self._lock:
            if record.id not in self._records:
                raise KeyError(f"Record with id {record.id} not found")
            self._records[record.id] = record
            self._dirty = True

    def get_record_by_id(self, record_id: str) -> UsageRecord | None:
        """Get a usage record by ID (thread-safe).

        Args:
            record_id: ID of the record to retrieve

        Returns:
            Usage record if found, None otherwise
        """
        with self._lock:
            return self._records.get(record_id)

    def is_dirty(self) -> bool:
        """Check if the store has been modified since last flush.

        Returns:
            True if store is dirty, False otherwise
        """
        with self._lock:
            return self._dirty

    def start_persistence_thread(self) -> None:
        """Start background thread for periodic persistence."""
        if self._flush_thread is not None and self._flush_thread.is_alive():
            logger.warning("Persistence thread already running")
            return

        self._shutdown_event.clear()
        self._flush_thread = threading.Thread(
            target=self._persistence_loop, daemon=True, name="UsageStorePersistence"
        )
        self._flush_thread.start()
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                f"Started persistence thread with {self._flush_interval}s interval"
            )

    def stop_persistence_thread(self) -> None:
        """Stop the background persistence thread and perform final flush."""
        if self._flush_thread is None or not self._flush_thread.is_alive():
            return

        logger.info("Stopping persistence thread...")
        self._shutdown_event.set()
        self._flush_thread.join(timeout=5.0)

        # Perform final flush
        self.flush_to_disk()
        logger.info("Persistence thread stopped")

    def _persistence_loop(self) -> None:
        """Background loop for periodic persistence."""
        while not self._shutdown_event.is_set():
            # Wait for flush interval or shutdown signal
            if self._shutdown_event.wait(timeout=self._flush_interval):
                break

            # Flush if dirty
            try:
                if self.is_dirty():
                    self.flush_to_disk()
            except Exception as e:
                logger.error(f"Error during periodic flush: {e}", exc_info=True)

    def flush_to_disk(self) -> None:
        """Persist current state to disk if dirty (thread-safe).

        This method serializes all records to JSON and writes them to the
        persistence file. The dirty flag is cleared after successful write.
        """
        with self._lock:
            if not self._dirty:
                logger.debug("Store is clean, skipping flush")
                return

            try:
                # Serialize records
                records_data = [record.to_dict() for record in self._records.values()]

                # Create persistence structure
                persistence_data = {
                    "version": 1,
                    "last_flush": datetime.now().isoformat(),
                    "record_count": len(records_data),
                    "records": records_data,
                }

                # Write to temporary file first
                temp_path = self._persistence_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(persistence_data, f, indent=2)

                # Atomic rename
                temp_path.replace(self._persistence_path)

                # Clear dirty flag
                self._dirty = False
                logger.info(
                    f"Flushed {len(records_data)} records to {self._persistence_path}"
                )

            except Exception as e:
                logger.error(f"Failed to flush to disk: {e}", exc_info=True)
                raise

    def load_from_disk(self) -> None:
        """Load persisted state from disk (thread-safe).

        This method reads the persistence file and loads all records into memory.
        If the file doesn't exist or is invalid, the store remains empty.
        """
        with self._lock:
            if not self._persistence_path.exists():
                logger.info(
                    f"No persistence file found at {self._persistence_path}, "
                    "starting with empty store"
                )
                return

            try:
                with open(self._persistence_path, encoding="utf-8") as f:
                    persistence_data = json.load(f)

                # Validate version
                version = persistence_data.get("version", 1)
                if version != 1:
                    logger.warning(
                        f"Unknown persistence version {version}, attempting to load"
                    )

                # Load records
                records_data = persistence_data.get("records", [])

                # Respect memory limit by taking only the most recent records
                if len(records_data) > self._max_records:
                    logger.info(
                        f"Truncating loaded records from {len(records_data)} to {self._max_records} limit"
                    )
                    records_data = records_data[-self._max_records :]

                loaded_count = 0

                for record_data in records_data:
                    try:
                        record = UsageRecord.from_dict(record_data)
                        self._records[record.id] = record
                        loaded_count += 1
                    except Exception as e:
                        logger.error(
                            f"Failed to load record {record_data.get('id')}: {e}",
                            exc_info=True,
                        )

                # Don't mark as dirty after loading
                self._dirty = False
                logger.info(
                    f"Loaded {loaded_count} records from {self._persistence_path}"
                )

            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse persistence file: {e}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"Failed to load from disk: {e}", exc_info=True)
                raise

    def clear(self) -> None:
        """Clear all records from the store (thread-safe).

        This method removes all records and marks the store as dirty.
        """
        with self._lock:
            self._records.clear()
            self._dirty = True

    def get_record_count(self) -> int:
        """Get the total number of records in the store (thread-safe).

        Returns:
            Number of records in the store
        """
        with self._lock:
            return len(self._records)
