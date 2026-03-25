"""RequestContext fork for Quality Verifier steering recall (main model, no nested QV)."""

from __future__ import annotations

import copy

from src.core.domain.request_context import RequestContext


def fork_request_context_for_quality_verifier_steering_recall(
    base: RequestContext,
) -> RequestContext:
    """Clone context with flags so recall skips QV and does not update session history like a user turn."""
    ext = copy.deepcopy(base.extensions) if base.extensions else {}
    ext["quality_verifier_skip_verification"] = True
    ext["auxiliary_request"] = True
    ext["call_purpose"] = "quality_verifier_steering_recall"
    return RequestContext(
        headers=base.headers,
        cookies=base.cookies,
        state=base.state,
        app_state=base.app_state,
        client_host=base.client_host,
        session_id=base.session_id,
        request_id=base.request_id,
        agent=base.agent,
        original_request=base.original_request,
        processing_context=copy.deepcopy(base.processing_context)
        if base.processing_context
        else None,
        domain_request=base.domain_request,
        raw_body=base.raw_body,
        backend=base.backend,
        effective_model=base.effective_model,
        requested_model=base.requested_model,
        extensions=ext,
        b2bua_identity=copy.deepcopy(base.b2bua_identity)
        if base.b2bua_identity
        else None,
        original_domain_request=base.original_domain_request,
    )
