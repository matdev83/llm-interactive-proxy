from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import cbor2

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.domain.cbor_capture import CaptureDirection, CapturedWireEvent

THINKER_INSTRUCTION_MARKER = "interleaved session thinker"
MEMO_INJECTION_MARKER = "The proxy captured this thinker memo"


def _iter_entries(path: Path):
    with path.open("rb") as handle:
        cbor2.load(handle)
        while True:
            try:
                yield CapturedWireEvent.from_dict(cbor2.load(handle))
            except cbor2.CBORDecodeEOF:
                return


def _body_from_http_request(raw: bytes) -> dict[str, Any] | None:
    marker = b"\r\n\r\n"
    pos = raw.find(marker)
    if pos < 0:
        return None
    body = raw[pos + len(marker) :]
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _has_thinker_instructions(messages: list[Any]) -> bool:
    if not messages:
        return False
    first = messages[0]
    if not isinstance(first, dict) or first.get("role") != "system":
        return False
    text = _message_text(first).lower()
    return THINKER_INSTRUCTION_MARKER in text


def _has_memo_injection(messages: list[Any]) -> bool:
    if not messages:
        return False
    first = messages[0]
    if not isinstance(first, dict) or first.get("role") != "system":
        return False
    return MEMO_INJECTION_MARKER in _message_text(first)


def _has_reasoning_content_injection(messages: list[Any]) -> bool:
    for message in messages:
        if isinstance(message, dict):
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return True
    return False


def _first_system_snippet(messages: list[Any]) -> str | None:
    if not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict) or first.get("role") != "system":
        return None
    return _message_text(first).replace("\n", " ")[:120]


def _first_reasoning_snippet(messages: list[Any]) -> str | None:
    for message in messages:
        if isinstance(message, dict):
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning.strip().replace("\n", " ")[:120]
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "usage: inspect_thinker_opencode_session.py <capture.cbor> <session-id>",
            file=sys.stderr,
        )
        return 2

    capture_path = Path(sys.argv[1])
    session_id = sys.argv[2]
    rows: list[dict[str, Any]] = []

    for entry in _iter_entries(capture_path):
        if entry.direction != CaptureDirection.PROXY_TO_BACKEND:
            continue
        if entry.backend != "opencode-go" or entry.session_id != session_id:
            continue
        payload = _body_from_http_request(entry.data)
        if payload is None:
            continue
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = []
        rows.append(
            {
                "seq": entry.sequence,
                "time": datetime.fromtimestamp(entry.timestamp).isoformat(
                    timespec="seconds"
                ),
                "model": payload.get("model"),
                "reasoning": payload.get("reasoning"),
                "reasoning_effort": payload.get("reasoning_effort"),
                "message_count": len(messages),
                "has_thinker_instructions": _has_thinker_instructions(messages),
                "has_memo_injection": _has_memo_injection(messages),
                "has_reasoning_content_injection": (
                    _has_reasoning_content_injection(messages)
                ),
                "first_role": (
                    messages[0].get("role")
                    if messages and isinstance(messages[0], dict)
                    else None
                ),
                "first_system_snippet": _first_system_snippet(messages),
                "first_reasoning_snippet": _first_reasoning_snippet(messages),
            }
        )

    print(json.dumps(rows, indent=2, sort_keys=True))
    thinker_count = sum(1 for row in rows if row["has_thinker_instructions"])
    memo_count = sum(1 for row in rows if row["has_memo_injection"])
    reasoning_content_count = sum(
        1 for row in rows if row["has_reasoning_content_injection"]
    )
    print(
        f"summary: outbound={len(rows)} thinker_instruction_requests={thinker_count} "
        f"memo_injected_requests={memo_count} "
        f"reasoning_content_injected_requests={reasoning_content_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
