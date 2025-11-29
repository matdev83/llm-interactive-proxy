
import cbor2
from pathlib import Path
import datetime
import time

# Define dummy CaptureFileHeader and CaptureEntry structure
# Based on tests/simulation/conftest.py and src/core/domain/cbor_capture.py
class DummyCaptureFileHeader:
    def __init__(self, session_id, metadata):
        self.session_id = session_id
        self.metadata = metadata
    def to_dict(self):
        return {"session_id": self.session_id, "metadata": self.metadata}

class DummyCaptureEntry:
    def __init__(self, timestamp, direction, sequence, data, metadata):
        self.timestamp = timestamp
        self.direction = direction
        self.sequence = sequence
        self.data = data
        self.metadata = metadata
    def to_dict(self):
        return {
            "ts": self.timestamp,
            "dir": self.direction,
            "seq": self.sequence,
            "data": self.data,
            "meta": self.metadata
        }

# Define dummy CaptureDirection enum as it's used in DummyCaptureEntry
class DummyCaptureDirection:
    CLIENT_TO_PROXY = 0  # Inbound request from client
    PROXY_TO_BACKEND = 2  # Outbound request to backend
    BACKEND_TO_PROXY = 3  # Inbound response/stream chunk from backend
    PROXY_TO_CLIENT = 1  # Outbound response/stream chunk to client

# Define the target path
capture_file_path = Path("var/wire_captures_cbor/c6095b51b3b844769f17469fefea2d89.cbor")
capture_file_path.parent.mkdir(parents=True, exist_ok=True)

# Create header
header = DummyCaptureFileHeader(
    session_id="test-session-123",
    metadata={"test_key": "test_value"}
)

# Create entries
entries = [
    DummyCaptureEntry(
        timestamp=time.time(),
        direction=DummyCaptureDirection.CLIENT_TO_PROXY,
        sequence=0,
        data=b'{"model": "test-model", "messages": []}',
        metadata={"session_id": "test-session-123", "prompt_tokens": 10}
    ),
    DummyCaptureEntry(
        timestamp=time.time() + 1,
        direction=DummyCaptureDirection.BACKEND_TO_PROXY,
        sequence=1,
        data=b'{"choices": [{"message": {"content": "Hello"}}]}',
        metadata={"session_id": "test-session-123", "completion_tokens": 5}
    )
]

# Write to file
with open(capture_file_path, "wb") as f:
    cbor2.dump(header.to_dict(), f)
    for entry in entries:
        cbor2.dump(entry.to_dict(), f)

print(f"Dummy capture file created at: {capture_file_path}")
