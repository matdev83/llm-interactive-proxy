"""Shared constants for CBOR wire capture inspection."""

from __future__ import annotations

CAPTURE_MAGIC = "LLMPROXY-CAPTURE-V2"
CAPTURE_VERSION = 2

DIRECTION_NAMES = {
    0: "CLIENT_TO_PROXY",
    1: "PROXY_TO_CLIENT",
    2: "PROXY_TO_BACKEND",
    3: "BACKEND_TO_PROXY",
}

DIRECTION_SYMBOLS = {
    0: "C->P",
    1: "P->C",
    2: "P->B",
    3: "B->P",
}

META_FIELD_NAMES = {
    "sid": "session_id",
    "asid": "a_session_id",
    "bsid": "b_session_id",
    "bseq": "b_seq",
    "be": "backend",
    "mod": "model",
    "key": "key_name",
    "host": "client_host",
    "ua": "user_agent",
    "rid": "request_id",
    "ci": "chunk_index",
    "ss": "is_stream_start",
    "se": "is_stream_end",
    "tc": "total_chunks",
    "tb": "total_bytes",
    "cu": "canonical_usage",
    "sc": "status_code",
    "ra": "retry_after_seconds",
    "rat": "retry_attempt",
    "rtry": "is_retry",
    "acct": "account_id",
    "rts": "request_timestamp",
    "pts": "response_timestamp",
    "lat": "latency_ms",
    "ttfb": "ttfb_ms",
    "sdur": "stream_duration_ms",
    "eos": "eos",
    "eos_sig": "eos_signal",
    "eos_reason": "eos_reason",
    "eos_term": "eos_termination_category",
    "eos_err_cls": "eos_error_classification",
    "eos_err_code": "eos_error_status_code",
    "wire_schema": "wire_schema",
    "transport": "transport",
    "event": "protocol_event",
    "http_method": "http_method",
    "url": "url",
    "http_status": "http_status_code",
    "http_reason": "http_reason_phrase",
    "http_version": "http_version",
    "ws_message_type": "websocket_message_type",
    "ccid": "compression_correlation_id",
    "crc": "compression_records_count",
    "cdb": "capture_debug",
}
