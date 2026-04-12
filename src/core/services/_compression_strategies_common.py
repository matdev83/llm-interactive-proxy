"""Shared regexes, logging, and helpers for compression strategies."""

from __future__ import annotations

import logging
import re

_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
_DCS_PM_APC_RE = re.compile(r"\x1B(?:P|_|\^)[\s\S]*?(?:\x1B\\)")
_ESC_SINGLE_RE = re.compile(r"\x1B[@-Z\\-_]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1A\x1C-\x1F\x7F-\x9F]")
_FAILURE_INDICATOR_RE = re.compile(
    r"(?i)\b("
    r"error|errors|failed|failure|fatal|panic|exception|traceback|"
    r"assertion(?:error)?|segmentation fault|stack trace|"
    r"timed out|timeout|denied"
    r")\b|^\s*E\s+|^\s*FAILED\b|^\s*FAIL\b"
)
_ZERO_FAILURE_RE = re.compile(r"(?i)\b(?:0\s+failed|0\s+failures|0\s+errors?)\b")
_POSITIVE_FAILURE_COUNT_RE = re.compile(
    r"(?i)\b[1-9]\d*\s+(?:failed|failures|errors?)\b"
)
logger = logging.getLogger("src.core.services.compression_strategies")

_REGEX_EVAL_SUBPROCESS_SNIPPET = (
    "import json\n"
    "import re\n"
    "import sys\n"
    "payload = json.loads(sys.stdin.read())\n"
    "try:\n"
    "    compiled = re.compile(payload['pattern'], payload['flags'])\n"
    "    matched = compiled.search(payload['text']) is not None\n"
    "except Exception:\n"
    "    matched = False\n"
    "sys.stdout.write('1' if matched else '0')\n"
)


def _line_indicates_failure(line: str) -> bool:
    if not _FAILURE_INDICATOR_RE.search(line):
        return False
    return not (
        _ZERO_FAILURE_RE.search(line) and not _POSITIVE_FAILURE_COUNT_RE.search(line)
    )


def _preserve_trailing_newline(*, original: str, transformed: str) -> str:
    """Keep only trailing-newline presence aligned to the source string."""
    if original.endswith("\n"):
        return transformed if transformed.endswith("\n") else f"{transformed}\n"
    return transformed.rstrip("\n")


_GIT_CMD_ERROR_RE = re.compile(r"^(fatal|error):\s", re.MULTILINE | re.IGNORECASE)
_GIT_CONFLICT_RE = re.compile(r"\bCONFLICT\b", re.IGNORECASE)
_COMMIT_HASH_IN_BRACKETS_RE = re.compile(
    r"\[([^\]\s]+)\s+([0-9a-f]{7,40})\]", re.IGNORECASE
)
_FILES_CHANGED_RE = re.compile(r"(\d+)\s+files?\s+changed", re.IGNORECASE)
_INSERTIONS_RE = re.compile(r"(\d+)\s+insertions?", re.IGNORECASE)
_DELETIONS_RE = re.compile(r"(\d+)\s+deletions?", re.IGNORECASE)
_REF_ARROW_RE = re.compile(
    r"^\s*([^\s]+\.{2,3}[^\s]+|[0-9a-f]{7,40}\.{2,3}[0-9a-f]{7,40})\s+(\S+)\s+->\s+(\S+)",
    re.MULTILINE,
)
_NPM_ERR_RE = re.compile(r"\bERR!\b", re.IGNORECASE)
_PIP_INSTALL_OK_RE = re.compile(
    r"Successfully installed\s+(.+)$", re.IGNORECASE | re.MULTILINE
)


def _mutating_ack_failure_heuristic(text: str) -> bool:
    if _GIT_CMD_ERROR_RE.search(text) or _GIT_CONFLICT_RE.search(text):
        return True
    if _NPM_ERR_RE.search(text):
        return True
    return any(_line_indicates_failure(line) for line in text.splitlines())
