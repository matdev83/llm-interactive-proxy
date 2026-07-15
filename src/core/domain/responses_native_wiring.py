"""Constants for wiring native Responses projector payloads through the backend stack."""

from __future__ import annotations

from dataclasses import dataclass

RESPONSES_NATIVE_PROJECTED_PAYLOAD_KEY = "responses_native_projected_payload"
ACP_RESPONSES_TEXT_ONLY_MODE_KEY = "acp_responses_text_only_mode"
# Internal marker used by ACP connectors to distinguish one-shot Responses
# requests from turns that are explicitly chained with ``previous_response_id``.
# This is never exposed on the public Responses wire.
ACP_RESPONSES_STANDALONE_MODE_KEY = "acp_responses_standalone_mode"


@dataclass(frozen=True)
class NativeResponsesContext:
    stream: bool
    session_id: str | None
