"""
CBOR capture file reader.

Parses CBOR capture files into replay-ready sequences for simulation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import BinaryIO

import cbor2

from src.core.domain.cbor_capture import (
    CaptureDirection,
    CaptureEntry,
    CaptureFileHeader,
    CaptureSession,
)

logger = logging.getLogger(__name__)


class CaptureReaderError(Exception):
    """Base exception for capture reader errors."""


# Maximum number of entries to load from capture file to prevent DoS attacks
MAX_CAPTURE_ENTRIES = 10000


class InvalidCaptureFileError(CaptureReaderError):
    """Raised when the capture file is invalid or corrupted."""


class CaptureReader:
    """Parse CBOR capture files into replay-ready sequences.

    Provides methods to load capture files, filter entries by direction,
    and compute timing information for replay.
    """

    def __init__(self) -> None:
        """Initialize the capture reader."""
        self._session: CaptureSession | None = None
        self._file_path: Path | None = None

    def load(self, path: Path | str) -> CaptureSession:
        """Load a CBOR capture file.

        Args:
            path: Path to the capture file

        Returns:
            CaptureSession with header and all entries

        Raises:
            InvalidCaptureFileError: If the file is invalid or corrupted
            FileNotFoundError: If the file doesn't exist
        """
        self._file_path = Path(path)

        if not self._file_path.exists():
            raise FileNotFoundError(f"Capture file not found: {self._file_path}")

        try:
            with open(self._file_path, "rb") as f:
                self._session = self._read_capture_file(f)
                return self._session
        except cbor2.CBORDecodeError as e:
            raise InvalidCaptureFileError(f"CBOR decode error: {e}") from e
        except Exception as e:
            raise InvalidCaptureFileError(f"Failed to read capture file: {e}") from e

    def _read_capture_file(self, f: BinaryIO) -> CaptureSession:
        """Read and parse a CBOR capture file.

        Args:
            f: Binary file handle

        Returns:
            CaptureSession with parsed header and entries
        """
        # Read header
        header_dict = cbor2.load(f)
        header = CaptureFileHeader.from_dict(header_dict)

        if not header.validate():
            raise InvalidCaptureFileError(
                f"Invalid capture file header: magic={header.magic}, version={header.version}"
            )

        # Read entries
        entries: list[CaptureEntry] = []
        while True:
            try:
                # DoS protection: Limit number of entries to prevent memory exhaustion
                if len(entries) >= MAX_CAPTURE_ENTRIES:
                    logger.warning(
                        "Reached maximum capture entries limit (%d), stopping load to prevent DoS",
                        MAX_CAPTURE_ENTRIES,
                    )
                    break

                entry_dict = cbor2.load(f)
                entry = CaptureEntry.from_dict(entry_dict)
                entries.append(entry)
            except cbor2.CBORDecodeEOF:
                break

        logger.debug(
            f"Loaded capture file: {len(entries)} entries, session_id={header.session_id}"
        )

        return CaptureSession(header=header, entries=entries)

    def get_session(self) -> CaptureSession:
        """Get the loaded capture session.

        Returns:
            The loaded CaptureSession

        Raises:
            RuntimeError: If no session has been loaded
        """
        if self._session is None:
            raise RuntimeError("No capture session loaded. Call load() first.")
        return self._session

    def get_client_sequence(self) -> list[CaptureEntry]:
        """Get entries for client-side traffic (inbound requests and outbound responses).

        Returns:
            List of entries with direction CLIENT_TO_PROXY or PROXY_TO_CLIENT
        """
        session = self.get_session()
        return session.get_client_entries()

    def get_backend_sequence(self) -> list[CaptureEntry]:
        """Get entries for backend-side traffic (outbound requests and inbound responses).

        Returns:
            List of entries with direction PROXY_TO_BACKEND or BACKEND_TO_PROXY
        """
        session = self.get_session()
        return session.get_backend_entries()

    def get_inbound_requests(self) -> list[CaptureEntry]:
        """Get all inbound request entries from client.

        Returns:
            List of entries with direction CLIENT_TO_PROXY
        """
        session = self.get_session()
        return session.get_inbound_request_entries()

    def get_outbound_responses(self) -> list[CaptureEntry]:
        """Get all outbound response entries to client.

        Returns:
            List of entries with direction PROXY_TO_CLIENT
        """
        session = self.get_session()
        return session.get_outbound_response_entries()

    def get_outbound_requests(self) -> list[CaptureEntry]:
        """Get all outbound request entries to backend.

        Returns:
            List of entries with direction PROXY_TO_BACKEND
        """
        session = self.get_session()
        return session.get_outbound_request_entries()

    def get_inbound_responses(self) -> list[CaptureEntry]:
        """Get all inbound response entries from backend.

        Returns:
            List of entries with direction BACKEND_TO_PROXY
        """
        session = self.get_session()
        return session.get_inbound_response_entries()

    def get_timing_deltas(self) -> list[float]:
        """Get time deltas between consecutive entries.

        Returns:
            List of delta times in seconds between entries
        """
        session = self.get_session()
        return session.get_timing_deltas()

    def get_stream_chunks(
        self, direction: CaptureDirection | None = None
    ) -> list[list[CaptureEntry]]:
        """Get streaming chunks grouped by stream session.

        Args:
            direction: Optional filter by direction

        Returns:
            List of lists, where each inner list is a complete stream
            (from stream_start to stream_end)
        """
        session = self.get_session()
        entries = session.entries

        if direction is not None:
            entries = [e for e in entries if e.direction == direction]

        streams: list[list[CaptureEntry]] = []
        current_stream: list[CaptureEntry] | None = None

        for entry in entries:
            if entry.metadata.is_stream_start:
                current_stream = [entry]
            elif current_stream is not None:
                current_stream.append(entry)
                if entry.metadata.is_stream_end:
                    streams.append(current_stream)
                    current_stream = None

        return streams

    def get_request_response_pairs(
        self,
    ) -> list[tuple[CaptureEntry, list[CaptureEntry]]]:
        """Get pairs of requests and their corresponding responses.

        For non-streaming responses, the list contains a single entry.
        For streaming responses, the list contains all stream chunks.

        Returns:
            List of (request_entry, response_entries) tuples
        """
        session = self.get_session()
        pairs: list[tuple[CaptureEntry, list[CaptureEntry]]] = []

        # Group entries by session_id
        by_session: dict[str, list[CaptureEntry]] = {}
        for entry in session.entries:
            sid = entry.metadata.session_id or "unknown"
            if sid not in by_session:
                by_session[sid] = []
            by_session[sid].append(entry)

        # For each session, pair requests with responses
        for _sid, entries in by_session.items():
            requests = [
                e
                for e in entries
                if e.direction
                in (CaptureDirection.CLIENT_TO_PROXY, CaptureDirection.PROXY_TO_BACKEND)
                and not e.metadata.is_stream_start
                and not e.metadata.is_stream_end
                and e.metadata.chunk_index is None
            ]

            for req in requests:
                # Find responses after this request
                req_idx = entries.index(req)
                responses = [
                    e
                    for e in entries[req_idx + 1 :]
                    if e.direction
                    in (
                        CaptureDirection.BACKEND_TO_PROXY,
                        CaptureDirection.PROXY_TO_CLIENT,
                    )
                ]

                if responses:
                    # Check if it's a streaming response
                    if any(r.metadata.is_stream_start for r in responses):
                        # Collect all stream entries
                        stream_responses = []
                        in_stream = False
                        for r in responses:
                            if r.metadata.is_stream_start:
                                in_stream = True
                            if in_stream:
                                stream_responses.append(r)
                                if r.metadata.is_stream_end:
                                    break
                        pairs.append((req, stream_responses))
                    else:
                        # Non-streaming response
                        pairs.append((req, [responses[0]]))

        return pairs

    def summarize(self) -> dict[str, object]:
        """Get a summary of the loaded capture.

        Returns:
            Dictionary with capture statistics
        """
        session = self.get_session()
        entries = session.entries

        direction_counts = {
            "client_to_proxy": 0,
            "proxy_to_client": 0,
            "proxy_to_backend": 0,
            "backend_to_proxy": 0,
        }

        stream_count = 0
        total_bytes = 0

        for entry in entries:
            if entry.direction == CaptureDirection.CLIENT_TO_PROXY:
                direction_counts["client_to_proxy"] += 1
            elif entry.direction == CaptureDirection.PROXY_TO_CLIENT:
                direction_counts["proxy_to_client"] += 1
            elif entry.direction == CaptureDirection.PROXY_TO_BACKEND:
                direction_counts["proxy_to_backend"] += 1
            elif entry.direction == CaptureDirection.BACKEND_TO_PROXY:
                direction_counts["backend_to_proxy"] += 1

            if entry.metadata.is_stream_start:
                stream_count += 1

            total_bytes += len(entry.data)

        timing = session.get_timing_deltas()
        duration = 0.0
        if len(entries) >= 2:
            duration = entries[-1].timestamp - entries[0].timestamp

        return {
            "session_id": session.header.session_id,
            "created_at": session.header.created_at,
            "total_entries": len(entries),
            "direction_counts": direction_counts,
            "stream_count": stream_count,
            "total_bytes": total_bytes,
            "duration_seconds": duration,
            "min_timing_delta": min(timing) if timing else 0,
            "max_timing_delta": max(timing) if timing else 0,
            "avg_timing_delta": sum(timing) / len(timing) if timing else 0,
        }
