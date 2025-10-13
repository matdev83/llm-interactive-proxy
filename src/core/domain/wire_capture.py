"""
Pydantic models for wire capture entries.

This module defines the data structures for wire capture entries,
replacing manual dictionary construction with type-safe Pydantic models.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class WireCaptureTimestamp(BaseModel):
    """Timestamp information for wire capture entries."""

    iso: str = Field(description="ISO format timestamp with milliseconds")
    human_readable: str = Field(description="Human-readable timestamp")


class WireCaptureCommunication(BaseModel):
    """Communication flow information for wire capture entries."""

    flow: str = Field(
        description="Communication flow direction (e.g., 'frontend_to_backend')"
    )
    direction: str = Field(
        description="Request/response direction (e.g., 'request', 'response')"
    )
    source: str = Field(description="Source of the communication")
    destination: str = Field(description="Destination of the communication")


class WireCaptureMetadata(BaseModel):
    """Metadata for wire capture entries."""

    session_id: str | None = Field(default=None, description="Session identifier")
    agent: str | None = Field(default=None, description="User agent information")
    backend: str = Field(description="Backend service name")
    model: str = Field(description="Model name")
    key_name: str | None = Field(default=None, description="API key name")
    byte_count: int | None = Field(default=None, description="Payload byte count")
    system_prompt: str | None = Field(
        default=None, description="Extracted system prompt"
    )


class WireCaptureEntry(BaseModel):
    """Complete wire capture entry with all required fields."""

    timestamp: WireCaptureTimestamp = Field(description="Timestamp information")
    communication: WireCaptureCommunication = Field(
        description="Communication flow information"
    )
    metadata: WireCaptureMetadata = Field(description="Entry metadata")
    payload: Any = Field(description="Request/response payload data")

    def model_dump(self, **kwargs) -> dict[str, Any]:
        """
        Convert to dictionary format expected by wire capture systems.

        Returns the entry in the expected wire capture format:
        {
            "timestamp": {
                "iso": str,
                "human_readable": str
            },
            "communication": {
                "flow": str,
                "direction": str,
                "source": str,
                "destination": str
            },
            "metadata": {
                "session_id": str,
                "agent": str,
                "backend": str,
                "model": str,
                "key_name": str,
                "byte_count": int,
                "system_prompt": str
            },
            "payload": Any
        }
        """
        return super().model_dump(**kwargs)


class BufferedWireCaptureEntry(BaseModel):
    """Wire capture entry for buffered capture service (NamedTuple replacement)."""

    timestamp: str = Field(description="Timestamp string")
    session_id: str | None = Field(default=None, description="Session identifier")
    backend: str = Field(description="Backend service name")
    model: str = Field(description="Model name")
    key_name: str | None = Field(default=None, description="API key name")
    direction: str = Field(description="Request/response direction")
    endpoint: str = Field(description="API endpoint")
    headers: dict[str, str] = Field(default_factory=dict, description="HTTP headers")
    payload: str = Field(description="Request/response payload as string")
    byte_count: int = Field(description="Payload byte count")
    client_host: str | None = Field(default=None, description="Client host information")
    agent: str | None = Field(default=None, description="User agent")
    system_prompt: str | None = Field(default=None, description="System prompt")

    def to_tuple(self):
        """Convert to tuple format for backward compatibility with NamedTuple usage."""
        return (
            self.timestamp,
            self.session_id,
            self.backend,
            self.model,
            self.key_name,
            self.direction,
            self.endpoint,
            self.headers,
            self.payload,
            self.byte_count,
            self.client_host,
            self.agent,
            self.system_prompt,
        )


def create_wire_capture_entry(
    *,
    flow: str,
    direction: str,
    context: Any = None,
    session_id: str | None = None,
    backend: str,
    model: str,
    key_name: str | None = None,
    payload: Any,
    byte_count: int | None = None,
    system_prompt: str | None = None,
) -> WireCaptureEntry:
    """
    Create a wire capture entry using Pydantic models.

    Args:
        flow: Communication flow direction
        direction: Request/response direction
        context: Request context (optional)
        session_id: Session identifier
        backend: Backend service name
        model: Model name
        key_name: API key name
        payload: Request/response payload
        byte_count: Payload byte count
        system_prompt: Extracted system prompt

    Returns:
        WireCaptureEntry with all fields populated
    """
    from datetime import timezone

    # Get timestamp in both ISO and human-readable formats
    utc_now = datetime.now(timezone.utc)
    iso_timestamp = utc_now.isoformat(timespec="milliseconds") + "Z"

    # Use local time for human-readable timestamp (based on system timezone)
    local_time = datetime.now()
    human_timestamp = local_time.strftime("%Y-%m-%d %H:%M:%S")

    # Extract source and destination info
    client_host = getattr(context, "client_host", None) if context else None
    agent = getattr(context, "agent", None) if context else None

    # Calculate byte count if not provided
    if byte_count is None:
        try:
            if isinstance(payload, str):
                byte_count = len(payload.encode("utf-8"))
            elif isinstance(payload, bytes):
                byte_count = len(payload)
            else:
                import json

                payload_str = json.dumps(payload, ensure_ascii=False)
                byte_count = len(payload_str.encode("utf-8"))
        except Exception:
            byte_count = -1

    # Create timestamp
    timestamp = WireCaptureTimestamp(
        iso=iso_timestamp,
        human_readable=human_timestamp,
    )

    # Create communication info
    communication = WireCaptureCommunication(
        flow=flow,
        direction=direction,
        source=(client_host or "unknown" if flow == "frontend_to_backend" else backend),
        destination=(
            backend if flow == "frontend_to_backend" else client_host or "unknown"
        ),
    )

    # Create metadata
    metadata = WireCaptureMetadata(
        session_id=session_id,
        agent=agent,
        backend=backend,
        model=model,
        key_name=key_name,
        byte_count=byte_count,
        system_prompt=system_prompt,
    )

    # Create the complete entry
    return WireCaptureEntry(
        timestamp=timestamp,
        communication=communication,
        metadata=metadata,
        payload=payload,
    )
