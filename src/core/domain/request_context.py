"""Request context utilities for backend services.

This module provides lightweight helpers that mirror the behaviour of the
project's richer pydantic models while remaining dependency free for tests and
utilities. Only the pieces required by the updated graceful-degradation logic
are implemented here.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic.types import JsonValue

from src.core.domain.chat import CanonicalChatRequest
from src.core.interfaces.model_bases import InternalDTO


class RequestHeaders(dict[str, str]):
    """Case-insensitive mapping for HTTP headers."""

    def __init__(self, raw: Mapping[str, Any] | None = None) -> None:
        normalized: dict[str, str] = {}
        if raw:
            for key, value in raw.items():
                normalized[str(key).lower()] = str(value)
        super().__init__(normalized)

    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        return super().get(key.lower(), default)

    def contains(self, key: str) -> bool:
        return key.lower() in self

    def to_dict(self) -> dict[str, str]:
        return dict(self)


class RequestCookies(dict[str, str]):
    """Simple cookie mapping used by middleware."""

    def __init__(self, raw: Mapping[str, Any] | None = None) -> None:
        normalized: dict[str, str] = {}
        if raw:
            for key, value in raw.items():
                normalized[str(key)] = str(value)
        super().__init__(normalized)

    def contains(self, key: str) -> bool:
        return key in self

    def to_dict(self) -> dict[str, str]:
        return dict(self)


@dataclass
class ContentModificationTracker:
    """Tracks content modifications for accurate usage calculation.

    This tracker monitors whether content has been modified during proxy processing,
    enabling accurate token recalculation for usage reporting.
    """

    # Inbound (request) modification tracking
    inbound_modified: bool = False
    inbound_original_tokens: int | None = None
    inbound_modified_tokens: int | None = None
    inbound_modification_reasons: list[str] = field(default_factory=list)

    # Outbound (response) modification tracking
    outbound_modified: bool = False
    outbound_original_tokens: int | None = None
    outbound_modified_tokens: int | None = None
    outbound_modification_reasons: list[str] = field(default_factory=list)

    def mark_inbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Mark that inbound (request) content was modified."""
        self.inbound_modified = True
        if reason and reason not in self.inbound_modification_reasons:
            self.inbound_modification_reasons.append(reason)
        if original_tokens is not None:
            self.inbound_original_tokens = original_tokens
        if modified_tokens is not None:
            self.inbound_modified_tokens = modified_tokens

    def mark_outbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Mark that outbound (response) content was modified."""
        self.outbound_modified = True
        if reason and reason not in self.outbound_modification_reasons:
            self.outbound_modification_reasons.append(reason)
        if original_tokens is not None:
            self.outbound_original_tokens = original_tokens
        if modified_tokens is not None:
            self.outbound_modified_tokens = modified_tokens

    def requires_usage_recalculation(self) -> bool:
        """Check if usage should be recalculated due to modifications."""
        return self.inbound_modified or self.outbound_modified

    def get_modification_summary(self) -> dict[str, Any]:
        """Get a summary of all modifications for logging/debugging."""
        return {
            "inbound_modified": self.inbound_modified,
            "inbound_reasons": self.inbound_modification_reasons,
            "inbound_token_delta": (
                (self.inbound_modified_tokens - self.inbound_original_tokens)
                if self.inbound_original_tokens is not None
                and self.inbound_modified_tokens is not None
                else None
            ),
            "outbound_modified": self.outbound_modified,
            "outbound_reasons": self.outbound_modification_reasons,
            "outbound_token_delta": (
                (self.outbound_modified_tokens - self.outbound_original_tokens)
                if self.outbound_original_tokens is not None
                and self.outbound_modified_tokens is not None
                else None
            ),
        }


@dataclass
class ProcessingContext:
    """Mutable context shared across middleware components."""

    values: dict[str, Any] = field(default_factory=dict)
    modification_tracker: ContentModificationTracker = field(
        default_factory=ContentModificationTracker
    )

    def update(self, data: Mapping[str, Any]) -> None:
        self.values.update(data)

    def mark_inbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Convenience method to mark inbound modification."""
        self.modification_tracker.mark_inbound_modified(
            reason, original_tokens, modified_tokens
        )

    def mark_outbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Convenience method to mark outbound modification."""
        self.modification_tracker.mark_outbound_modified(
            reason, original_tokens, modified_tokens
        )


@dataclass
class RequestContext(InternalDTO):
    """Transport-agnostic request context used by core services."""

    headers: RequestHeaders | Mapping[str, Any]
    cookies: RequestCookies | Mapping[str, Any]
    state: Any
    app_state: Any
    client_host: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    agent: str | None = None
    original_request: Any | None = None
    processing_context: ProcessingContext | None = None
    # Explicit typed fields for cross-layer data exchange
    domain_request: CanonicalChatRequest | None = None
    raw_body: bytes | None = None
    backend: str | None = None
    effective_model: str | None = None
    requested_model: str | None = None
    extensions: dict[str, JsonValue] = field(default_factory=dict)
    """
    Extension container for vendor- and protocol-specific data.
    
    This is the single, explicitly named extension container permitted to remain
    open-ended for cross-layer data exchange. All values must be JSON-serializable
    (JsonValue: str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]).
    
    Extension fields should be used sparingly and only when:
    - The data is vendor/protocol-specific and not part of the canonical contract
    - The data is needed across layers but doesn't warrant a first-class typed field
    
    Frequently-used extension keys should be promoted to first-class typed fields
    in RequestContext or domain models when they become stable.
    """
    # Provenance tracking: store original contract values for debugging/accounting
    original_domain_request: CanonicalChatRequest | None = None
    """Original domain request before any mutations (copy-on-write provenance).
    
    This field stores the original contract instance before any transformations
    are applied. It enables debugging and accounting by providing access to
    the original values even after mutations occur.
    
    Requirement 5.3: When modifications occur, the LLM Proxy shall retain
    provenance sufficient for debugging and accounting, including the reason
    for modification and the ability to access the original value.
    """

    def __post_init__(self) -> None:
        if not isinstance(self.headers, RequestHeaders):
            self.headers = RequestHeaders(self.headers)  # type: ignore[arg-type]
        if not isinstance(self.cookies, RequestCookies):
            self.cookies = RequestCookies(self.cookies)  # type: ignore[arg-type]
        if self.processing_context is not None and not isinstance(
            self.processing_context, ProcessingContext
        ):  # type: ignore[reportUnnecessaryIsInstance]
            self.processing_context = ProcessingContext(
                values=dict(self.processing_context)  # type: ignore[arg-type]
            )

    def get_header(self, key: str, default: str | None = None) -> str | None:
        return self.headers.get(key, default)

    def get_cookie(self, key: str, default: str | None = None) -> str | None:
        return self.cookies.get(key, default)

    def with_processing_context(self, **kwargs: Any) -> RequestContext:
        new_context = (
            ProcessingContext(
                values=dict(self.processing_context.values),
                modification_tracker=self.processing_context.modification_tracker,
            )
            if self.processing_context
            else ProcessingContext(values={})
        )
        new_context.update(kwargs)
        return RequestContext(
            headers=RequestHeaders(self.headers),
            cookies=RequestCookies(self.cookies),
            state=self.state,
            app_state=self.app_state,
            client_host=self.client_host,
            session_id=self.session_id,
            request_id=self.request_id,
            agent=self.agent,
            original_request=self.original_request,
            processing_context=new_context,
            domain_request=self.domain_request,
            raw_body=self.raw_body,
            backend=self.backend,
            effective_model=self.effective_model,
            requested_model=self.requested_model,
            extensions=copy.deepcopy(self.extensions) if self.extensions else {},
            original_domain_request=self.original_domain_request,
        )

    def ensure_processing_context(self) -> ProcessingContext:
        """Ensure processing context exists and return it."""
        if self.processing_context is None:
            self.processing_context = ProcessingContext()
        return self.processing_context

    def get_modification_tracker(self) -> ContentModificationTracker:
        """Get the modification tracker, creating processing context if needed."""
        return self.ensure_processing_context().modification_tracker

    def mark_inbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Mark that inbound (request) content was modified."""
        self.get_modification_tracker().mark_inbound_modified(
            reason, original_tokens, modified_tokens
        )

    def mark_outbound_modified(
        self,
        reason: str,
        original_tokens: int | None = None,
        modified_tokens: int | None = None,
    ) -> None:
        """Mark that outbound (response) content was modified."""
        self.get_modification_tracker().mark_outbound_modified(
            reason, original_tokens, modified_tokens
        )

    def requires_usage_recalculation(self) -> bool:
        """Check if usage should be recalculated due to content modifications."""
        if self.processing_context is None:
            return False
        return (
            self.processing_context.modification_tracker.requires_usage_recalculation()
        )

    def capture_original_domain_request(self, request: CanonicalChatRequest) -> None:
        """Capture the original domain request for provenance tracking.

        This method stores the original contract instance before any mutations
        occur. It should be called when the domain_request is first set.

        Requirement 5.3: When modifications occur, the LLM Proxy shall retain
        provenance sufficient for debugging and accounting, including the reason
        for modification and the ability to access the original value.

        Args:
            request: The original domain request to capture
        """
        if self.original_domain_request is None:
            self.original_domain_request = request

    def get_original_domain_request(self) -> CanonicalChatRequest | None:
        """Get the original domain request before any mutations.

        Returns:
            The original domain request, or None if not captured
        """
        return self.original_domain_request
