"""``ConnectorRequestContext.extensions`` keys for HTTP wire capture (CBOR).

Values must be JSON-safe (``str``, ``int``, ``bool``) so they flow through
``ConnectorRequestContext`` and into CBOR metadata unchanged.
"""

from __future__ import annotations

# Managed OAuth / backend account identifier (non-secret), e.g. ChatGPT account UUID.
WIRE_CAPTURE_ACCOUNT_ID_KEY = "wire_capture_account_id"
# Zero-based logical attempt index for this upstream HTTP interaction (handshake / retry).
WIRE_CAPTURE_RETRY_ATTEMPT_KEY = "wire_capture_retry_attempt"
# True when ``retry_attempt`` > 0 (rotation, auth retry, or transport-level resend).
WIRE_CAPTURE_IS_RETRY_KEY = "wire_capture_is_retry"
