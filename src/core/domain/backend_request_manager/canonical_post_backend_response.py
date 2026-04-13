"""Canonical post-backend-response contracts (manager boundary, Phase 1)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum

from pydantic.types import JsonValue

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse


class PostBackendProcessingMode(str, Enum):
    """Post-backend dispatch for the canonical coordinator.

    Selection happens at the manager boundary; the coordinator does not read the
    client's ``stream`` flag from the request.

    Blocking ``ResponseEnvelope`` inputs are wrapped as a single-chunk stream and
    always run through the streaming handler. Native ``StreamingResponseEnvelope``
    inputs also always use the streaming handler so post-backend logic is a
    single path; the client transport shape is chosen only at the boundary via
    :class:`~src.core.services.envelope_compatibility_adapter.EnvelopeCompatibilityAdapter`.

    ``RAW_PASSTHROUGH`` is retained only for backward compatibility with older
    call sites; the manager always selects ``STREAMING_HANDLER``.
    """

    STREAMING_HANDLER = "streaming_handler"
    RAW_PASSTHROUGH = "raw_passthrough"


def select_post_backend_processing_mode(
    requested_stream: bool,
    backend_response: ResponseEnvelope | StreamingResponseEnvelope,
    *,
    connector_stream_first_active: bool = False,
) -> PostBackendProcessingMode:
    """Return post-backend mode for the canonical coordinator (always streaming handler).

    Arguments are accepted for a stable API and for callers that still thread
    migration-era parameters; they do not change the result under canonical-only
    runtime.
    """
    del requested_stream, backend_response, connector_stream_first_active
    return PostBackendProcessingMode.STREAMING_HANDLER


@dataclass
class CanonicalResponseHandle:
    """Internal manager-level handle: canonical chunk stream plus envelope metadata."""

    stream: AsyncIterator[ProcessedResponse]
    status_code: int
    media_type: str
    headers: dict[str, str] | None
    cancel_callback: Callable[[], Awaitable[None]] | None
    usage: UsageSummary | None
    canonical_usage: CanonicalUsageRecord | None
    metadata: dict[str, JsonValue] = field(default_factory=dict)
