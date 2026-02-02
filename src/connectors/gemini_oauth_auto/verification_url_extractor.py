"""Helpers for detecting Gemini OAuth account verification URLs."""

from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://[^\s)\]>\"']+", re.IGNORECASE)


def extract_first_url(text: str | None) -> str | None:
    """Extract the first URL found in a text blob.

    The errors we see from Gemini/Google sometimes contain a line break before the URL
    and may include trailing punctuation. We keep the heuristic simple and safe.
    """

    if not isinstance(text, str) or not text.strip():
        return None

    match = _URL_RE.search(text)
    if not match:
        return None

    url = match.group(0).strip()
    # Strip common trailing punctuation that often appears in log strings.
    return url.rstrip(".,;")
