from __future__ import annotations

import cbor2
import pytest
from src.core.simulation.capture_reader import CaptureReader


def test_capture_reader_best_effort_stops_on_invalid_utf8(tmp_path) -> None:
    """CaptureReader should not fail the entire capture if a later CBOR item is malformed.

    We simulate a capture file with:
    - valid header dict
    - one valid entry dict
    - a malformed CBOR item containing an invalid UTF-8 text string

    The reader should load the header and the valid entry, then stop.
    """

    capture_path = tmp_path / "bad.cbor"

    header = {
        "magic": "LLMPROXY-CAPTURE-V1",
        "version": 1,
        "created_at": 0.0,
        "session_id": "test",
        "metadata": {},
    }
    entry_ok = {
        "ts": 0.0,
        "dir": 0,
        "seq": 1,
        "data": b"{}",
    }

    # CBOR text major type (3), 1-byte length (24..255) => 0x78 <len>
    # Provide invalid UTF-8 bytes (0xff) so cbor2 raises "error decoding unicode string".
    invalid_text_item = bytes([0x78, 0x01, 0xFF])

    with capture_path.open("wb") as f:
        f.write(cbor2.dumps(header))
        f.write(cbor2.dumps(entry_ok))
        f.write(invalid_text_item)

    reader = CaptureReader()

    # Should not raise
    session = reader.load(capture_path)

    assert session.header.session_id == "test"
    assert len(session.entries) == 1
    assert session.entries[0].sequence == 1


@pytest.mark.parametrize(
    "args",
    [
        ("--status-summary",),
        ("--detect-issues", "--last", "5"),
    ],
)
def test_inspect_script_loader_best_effort_does_not_crash(
    tmp_path, args, capsys
) -> None:
    """The inspection tool's loader should also be robust.

    We call its internal load_capture_file() via import and ensure it returns
    a prefix rather than raising.
    """

    # Import here so the script's sys.path manipulation doesn't affect collection.
    import scripts.inspect_cbor_capture as inspector

    capture_path = tmp_path / "bad.cbor"

    header = {
        "magic": "LLMPROXY-CAPTURE-V1",
        "version": 1,
        "created_at": 0.0,
        "session_id": "test",
        "metadata": {},
    }
    entry_ok = {
        "ts": 0.0,
        "dir": 0,
        "seq": 1,
        "data": b"{}",
    }

    invalid_text_item = bytes([0x78, 0x01, 0xFF])

    with capture_path.open("wb") as f:
        f.write(cbor2.dumps(header))
        f.write(cbor2.dumps(entry_ok))
        f.write(invalid_text_item)

    loaded_header, entries = inspector.load_capture_file(capture_path)
    assert loaded_header["session_id"] == "test"
    assert len(entries) == 1

    # Ensure warning emitted
    _out = capsys.readouterr()
    # Warning goes to stderr
    assert "WARNING: stopping early" in _out.err
