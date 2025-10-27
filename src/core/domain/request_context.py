"""Request context utilities for backend services.

This module provides lightweight helpers that mirror the behaviour of the
project's richer pydantic models while remaining dependency free for tests and
utilities. Only the pieces required by the updated graceful-degradation logic
are implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

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
class ProcessingContext:
    """Mutable context shared across middleware components."""

    values: dict[str, Any] = field(default_factory=dict)

    def update(self, data: Mapping[str, Any]) -> None:
        self.values.update(data)


@dataclass
class RequestContext(InternalDTO):
    """Transport-agnostic request context used by core services."""

    headers: RequestHeaders | Mapping[str, Any]
    cookies: RequestCookies | Mapping[str, Any]
    state: Any
    app_state: Any
    client_host: str | None = None
    session_id: str | None = None
    agent: str | None = None
    original_request: Any | None = None
    processing_context: ProcessingContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.headers, RequestHeaders):
            self.headers = RequestHeaders(self.headers)  # type: ignore[arg-type]
        if not isinstance(self.cookies, RequestCookies):
            self.cookies = RequestCookies(self.cookies)  # type: ignore[arg-type]
        if self.processing_context is not None and not isinstance(
            self.processing_context, ProcessingContext
        ):
            self.processing_context = ProcessingContext(
                values=dict(self.processing_context)  # type: ignore[arg-type]
            )

    def get_header(self, key: str, default: str | None = None) -> str | None:
        return self.headers.get(key, default)

    def get_cookie(self, key: str, default: str | None = None) -> str | None:
        return self.cookies.get(key, default)

    def with_processing_context(self, **kwargs: Any) -> RequestContext:
        new_context = (
            ProcessingContext(values=dict(self.processing_context.values))
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
            agent=self.agent,
            original_request=self.original_request,
            processing_context=new_context,
        )
