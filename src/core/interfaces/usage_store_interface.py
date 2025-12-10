"""Interface for usage record storage.

This module defines the protocol for usage record stores, allowing different
implementations (in-memory, SQL, etc.) to be used interchangeably.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.core.domain.statistics_filter import StatisticsFilter
    from src.core.domain.usage_record import UsageRecord


@runtime_checkable
class IUsageStore(Protocol):
    """Protocol for usage record storage.

    This protocol defines the interface that all usage stores must implement,
    allowing different backends (in-memory, SQL, etc.) to be used interchangeably.
    """

    def add_record(self, record: UsageRecord) -> None:
        """Add a usage record to the store.

        Args:
            record: Usage record to add
        """
        ...

    def get_records(self, filters: StatisticsFilter | None = None) -> list[UsageRecord]:
        """Get usage records matching the filter.

        Args:
            filters: Optional filter to apply. If None, returns all records.

        Returns:
            List of usage records matching the filter
        """
        ...

    def update_record(self, record: UsageRecord) -> None:
        """Update an existing usage record.

        Args:
            record: Usage record to update

        Raises:
            KeyError: If record with given ID does not exist
        """
        ...

    def get_record_by_id(self, record_id: str) -> UsageRecord | None:
        """Get a usage record by ID.

        Args:
            record_id: ID of the record to retrieve

        Returns:
            Usage record if found, None otherwise
        """
        ...

    def is_dirty(self) -> bool:
        """Check if the store has been modified since last flush.

        Returns:
            True if store is dirty, False otherwise
        """
        ...

    def start_persistence_thread(self) -> None:
        """Start background thread for periodic persistence."""
        ...

    def stop_persistence_thread(self) -> None:
        """Stop the background persistence thread."""
        ...

    def flush_to_disk(self) -> None:
        """Persist current state to disk."""
        ...

    def load_from_disk(self) -> None:
        """Load persisted state from disk."""
        ...

    def clear(self) -> None:
        """Clear all records from the store."""
        ...

    def get_record_count(self) -> int:
        """Get the total number of records in the store.

        Returns:
            Number of records in the store
        """
        ...
