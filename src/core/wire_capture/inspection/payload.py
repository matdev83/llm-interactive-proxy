"""Payload decoding: SSE, safe text preview, hexdump."""

from __future__ import annotations

import json
from typing import Any


def safe_decode(data: bytes, max_length: int = 200) -> str:
    """Safely decode bytes to string, handling non-ASCII."""
    if not data:
        return "(empty)"
    text = data[:max_length].decode("utf-8", errors="replace")
    result = []
    for char in text:
        if ord(char) < 32 and char not in "\n\r\t":
            result.append(f"\\x{ord(char):02x}")
        elif ord(char) >= 128:
            result.append(f"\\u{ord(char):04x}")
        else:
            result.append(char)
    return "".join(result)


def parse_all_sse_events(data: bytes) -> list[dict[str, Any]]:
    """Parse all SSE data chunks in a payload into a list of JSON objects."""
    if not data:
        return []
    text = data.decode("utf-8", errors="replace").strip()

    results: list[dict[str, Any]] = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    result: dict[str, Any] = json.loads(json_str)
                    results.append(result)
                except json.JSONDecodeError:
                    continue
    return results


def parse_sse_chunk(data: bytes) -> dict[str, Any] | None:
    """Return first SSE JSON event, if any."""
    events = parse_all_sse_events(data)
    return events[0] if events else None


def hexdump(data: bytes, length: int = 16) -> list[str]:
    """Generate a canonical hex dump of the data."""
    result: list[str] = []
    for i in range(0, len(data), length):
        chunk = data[i : i + length]
        hex_line = " ".join(f"{b:02x}" for b in chunk)
        ascii_line = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        result.append(f"{i:04x}  {hex_line:<{length * 3}}  |{ascii_line}|")
    return result
