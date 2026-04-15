"""Write human-readable lines to text streams (no print())."""

from __future__ import annotations

import sys
from typing import TextIO


def writeln(stream: TextIO | None, *parts: object, sep: str = " ") -> None:
    """Write ``parts`` joined by ``sep`` and append a newline."""
    sink = stream or sys.stdout
    if parts:
        sink.write(sep.join(str(p) for p in parts))
    sink.write("\n")
