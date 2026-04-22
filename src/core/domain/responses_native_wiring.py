"""Constants for wiring native Responses projector payloads through the backend stack."""

from __future__ import annotations

from dataclasses import dataclass

RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY = "responses_native_projected_payload"


@dataclass(frozen=True)
class NativeResponsesContext:
    stream: bool
    session_id: str | None
