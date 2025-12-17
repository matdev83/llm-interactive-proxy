from __future__ import annotations

from enum import Enum

from pydantic import ConfigDict

from src.core.interfaces.model_bases import DomainModel


class LogLevel(str, Enum):
    """Log levels for configuration."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LoggingConfig(DomainModel):
    """Logging configuration."""

    model_config = ConfigDict(frozen=True)

    level: LogLevel = LogLevel.INFO
    use_colors: bool = False
    request_logging: bool = False
    response_logging: bool = False
    log_file: str | None = None
    # Optional separate wire-capture log file; when set, all outbound requests
    # and inbound replies/SSE payloads are captured verbatim to this file.
    capture_file: str | None = None
    # Optional max size in bytes; when exceeded, rotate current capture to
    # `<capture_file>.1` and start a new file (overwrite existing .1).
    capture_max_bytes: int | None = None
    # Optional per-chunk truncation size in bytes for streaming capture. When
    # set, stream chunks written to capture are truncated to this size with a
    # short marker appended; streaming to client remains unmodified.
    capture_truncate_bytes: int | None = None
    # Optional number of rotated files to keep (e.g., file.1..file.N). If not
    # set or <= 0, keeps a single rotation (file.1). Used only when
    # capture_max_bytes is set.
    capture_max_files: int | None = None
    # Time-based rotation period in seconds (default 1 day). If set <= 0, time
    # rotation is disabled.
    capture_rotate_interval_seconds: int = 86400
    # Total disk cap across current capture file and rotated files. If set <= 0,
    # disabled. Default is 100 MiB.
    capture_total_max_bytes: int = 104857600
    # Buffer size for wire capture writes (bytes). Default 64KB.
    capture_buffer_size: int = 65536
    # How often to flush buffer to disk (seconds). Default 1.0 second.
    capture_flush_interval: float = 1.0
    # Maximum entries to buffer before forcing flush. Default 100.
    capture_max_entries_per_flush: int = 100

    # CBOR byte-precise capture configuration (optional, complementary to JSON capture)
    # Directory for CBOR capture files; when set, enables CBOR capture with byte precision
    cbor_capture_dir: str | None = None
    # Optional fixed session ID for CBOR capture; auto-generated if not provided
    cbor_capture_session_id: str | None = None
