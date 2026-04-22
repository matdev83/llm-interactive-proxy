"""Protocol for projecting Responses domain requests to provider wire payloads."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.core.domain.responses_domain import ResponsesDomainRequest, ResponsesOutputItem


@runtime_checkable
class IResponsesBackendProjector(Protocol):
    def project(
        self,
        request: ResponsesDomainRequest,
        prior_items: list[ResponsesOutputItem] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Return (provider_payload, capability_flags).

        capability_flags lists features that could not be preserved for the provider.
        """
        ...
