"""Adapter that resolves composite leaf selectors via BackendModelResolver."""

from __future__ import annotations

from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.model_utils import (
    RESOLVED_URI_PARAMS_EXTRA_BODY_KEY,
    has_explicit_backend_selector,
    parse_model_with_params,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_model_resolver_interface import IBackendModelResolver
from src.core.services.composite_routing_state import (
    COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY,
    COMPOSITE_LEAF_RESOLUTION_FLAG,
    COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY,
)

__all__ = ["CompositeLeafTargetResolverAdapter"]


class CompositeLeafTargetResolverAdapter:
    """Resolves one composite leaf while preserving existing selector semantics."""

    def __init__(self, backend_model_resolver: IBackendModelResolver) -> None:
        self._backend_model_resolver = backend_model_resolver

    async def resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf_selector: str,
    ) -> BackendTarget:
        leaf_extra_body = dict(request.extra_body or {})
        leaf_extra_body[COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY] = True
        leaf_extra_body[COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY] = leaf_selector

        parsed_leaf = parse_model_with_params(leaf_selector, default_backend="")
        if has_explicit_backend_selector(leaf_selector):
            leaf_extra_body[RESOLVED_URI_PARAMS_EXTRA_BODY_KEY] = dict(
                parsed_leaf.uri_params
            )
            leaf_extra_body.pop("backend_type", None)
        elif parsed_leaf.uri_params:
            leaf_extra_body[RESOLVED_URI_PARAMS_EXTRA_BODY_KEY] = dict(
                parsed_leaf.uri_params
            )

        leaf_request = request.model_copy(
            update={
                "model": leaf_selector,
                "extra_body": leaf_extra_body,
            }
        )

        if context is None:
            return await self._backend_model_resolver.resolve_target(
                request=leaf_request,
                context=None,
            )

        previous_flag = context.extensions.get(COMPOSITE_LEAF_RESOLUTION_FLAG)
        context.extensions[COMPOSITE_LEAF_RESOLUTION_FLAG] = True
        try:
            return await self._backend_model_resolver.resolve_target(
                request=leaf_request,
                context=context,
            )
        finally:
            if previous_flag is None:
                context.extensions.pop(COMPOSITE_LEAF_RESOLUTION_FLAG, None)
            else:
                context.extensions[COMPOSITE_LEAF_RESOLUTION_FLAG] = previous_flag
