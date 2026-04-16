"""Normalize shell command strings before dangerous-pattern matching.

Mitigations inspired by Hermes ``approval.py`` / ``_normalize_command_for_detection``:
ANSI escape stripping, NUL removal, Unicode NFKC (homoglyph / fullwidth evasion).
"""

from __future__ import annotations

import re
import unicodedata

# CSI / SGR sequences: ESC [ ... final byte 0x40-0x7E
_CSI_OR_SGR = re.compile(r"\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]")
# OSC sequences (e.g. hyperlinks): ESC ] ... BEL or ST
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def normalize_command_for_security_scan(command: str) -> str:
    """Strip obfuscation and terminal noise so regex matchers see the real tokens.

    Order: remove NULs, strip OSC/CSI ANSI, then Unicode NFKC.
    """
    s = command.replace("\x00", "")
    s = _OSC.sub("", s)
    s = _CSI_OR_SGR.sub("", s)
    return unicodedata.normalize("NFKC", s)
