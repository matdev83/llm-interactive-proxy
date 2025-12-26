"""Domain models for connection activity tracking.

This module provides dataclasses for tracking active connections through
backend connectors, including RX/TX byte counters per session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel


class ConnectionType(str, Enum):
    """Type of connection being tracked."""

    STREAMING = "streaming"
    NON_STREAMING = "non_streaming"


class ConnectionActivityDict(BaseModel):
    """Serialized form of ConnectionActivity for API responses."""

    session_id: str
    backend_name: str
    connection_type: str
    started_at: float
    duration_seconds: float
    model: str | None
    bytes_rx: int
    bytes_tx: int


class BackendActivitySnapshotDict(BaseModel):
    """Serialized form of BackendActivitySnapshot for API responses."""

    backend_name: str
    active_connections: int
    connections: list[ConnectionActivityDict]
    total_bytes_rx: int
    total_bytes_tx: int


class GlobalActivitySnapshotDict(BaseModel):
    """Serialized form of GlobalActivitySnapshot for API responses."""

    timestamp: float
    backends: list[BackendActivitySnapshotDict]
    total_active_connections: int
    total_bytes_rx: int
    total_bytes_tx: int


@dataclass
class ConnectionActivity:
    """Represents an active connection through a backend connector.

    Attributes:
        session_id: Unique identifier for the session/request.
        backend_name: Name of the backend instance handling this connection.
        connection_type: Whether this is a streaming or non-streaming request.
        started_at: Unix timestamp when the connection started.
        model: The model being used (if known).
        bytes_rx: Total bytes received from the backend.
        bytes_tx: Total bytes transmitted to the client.
    """

    session_id: str
    backend_name: str
    connection_type: ConnectionType
    started_at: float = field(default_factory=time.time)
    model: str | None = None
    bytes_rx: int = 0
    bytes_tx: int = 0

    @property
    def duration_seconds(self) -> float:
        """Get the duration of the connection in seconds."""
        return time.time() - self.started_at

    def to_dict(self) -> ConnectionActivityDict:
        """Convert to dictionary for API serialization."""
        return ConnectionActivityDict(
            session_id=self.session_id,
            backend_name=self.backend_name,
            connection_type=self.connection_type.value,
            started_at=self.started_at,
            duration_seconds=round(self.duration_seconds, 3),
            model=self.model,
            bytes_rx=self.bytes_rx,
            bytes_tx=self.bytes_tx,
        )


@dataclass
class BackendActivitySnapshot:
    """Snapshot of activity for a single backend instance.

    Attributes:
        backend_name: Name of the backend instance.
        active_connections: Number of currently active connections.
        connections: List of active connection details.
        total_bytes_rx: Total bytes received across all active connections.
        total_bytes_tx: Total bytes transmitted across all active connections.
    """

    backend_name: str
    active_connections: int = 0
    connections: list[ConnectionActivity] = field(default_factory=list)
    total_bytes_rx: int = 0
    total_bytes_tx: int = 0

    def to_dict(self) -> BackendActivitySnapshotDict:
        """Convert to dictionary for API serialization."""
        return BackendActivitySnapshotDict(
            backend_name=self.backend_name,
            active_connections=self.active_connections,
            connections=[c.to_dict() for c in self.connections],
            total_bytes_rx=self.total_bytes_rx,
            total_bytes_tx=self.total_bytes_tx,
        )


@dataclass
class GlobalActivitySnapshot:
    """Global snapshot of all backend activity.

    Attributes:
        timestamp: Unix timestamp when the snapshot was taken.
        backends: List of per-backend activity snapshots.
        total_active_connections: Total active connections across all backends.
        total_bytes_rx: Total bytes received across all backends.
        total_bytes_tx: Total bytes transmitted across all backends.
    """

    timestamp: float = field(default_factory=time.time)
    backends: list[BackendActivitySnapshot] = field(default_factory=list)
    total_active_connections: int = 0
    total_bytes_rx: int = 0
    total_bytes_tx: int = 0

    def to_dict(self) -> GlobalActivitySnapshotDict:
        """Convert to dictionary for API serialization."""
        return GlobalActivitySnapshotDict(
            timestamp=self.timestamp,
            backends=[b.to_dict() for b in self.backends],
            total_active_connections=self.total_active_connections,
            total_bytes_rx=self.total_bytes_rx,
            total_bytes_tx=self.total_bytes_tx,
        )
