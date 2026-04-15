"""Load CBOR wire capture files for inspection (no entry-count cap)."""

from __future__ import annotations

import sys
import zlib
from pathlib import Path
from typing import Any

import cbor2

from src.core.wire_capture.inspection.metadata import validate_capture_header
from src.core.wire_capture.inspection.text_output import writeln


def load_capture_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a CBOR capture file and return header and entries.

    Unlike simulation ``CaptureReader``, this does not cap the number of entries,
    so large captures can be inspected in full.
    """
    entries: list[dict[str, Any]] = []
    with open(path, "rb") as f:
        header = cbor2.load(f)
        validate_capture_header(header)
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break
            except cbor2.CBORDecodeError as e:
                writeln(
                    sys.stderr,
                    "WARNING: stopping early due to CBOR decode error after "
                    f"{len(entries)} entries: {e}",
                )
                break
    return header, entries
