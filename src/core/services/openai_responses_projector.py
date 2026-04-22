"""OpenAI Responses API: native wire projection (no chat flattening)."""

from __future__ import annotations

from typing import Any

from src.core.domain.responses_domain import ResponsesDomainRequest, ResponsesOutputItem
from src.core.interfaces.responses_projector import IResponsesBackendProjector


class OpenAIResponsesProjector(IResponsesBackendProjector):
    def project(
        self,
        request: ResponsesDomainRequest,
        prior_items: list[ResponsesOutputItem] | None,
    ) -> tuple[dict[str, Any], list[str]]:
        _ = prior_items
        payload = request.model_dump(
            mode="json",
            exclude_unset=True,
            exclude_none=True,
        )
        extra_body = payload.pop("extra_body", None)
        if isinstance(extra_body, dict):
            merged: dict[str, Any] = {**payload, **extra_body}
            return merged, []
        return payload, []
