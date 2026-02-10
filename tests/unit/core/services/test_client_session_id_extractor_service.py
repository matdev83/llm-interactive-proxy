from __future__ import annotations

from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.services.client_session_id_extractor_service import (
    DefaultClientSessionIdExtractor,
)


def _make_context(
    *,
    headers: dict[str, str] | None = None,
    body_session_id: str | None = None,
    extra_body_session_id: str | None = None,
) -> RequestContext:
    domain_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hello")],
        session_id=body_session_id,
        extra_body=(
            {"session_id": extra_body_session_id}
            if extra_body_session_id is not None
            else None
        ),
    )
    return RequestContext(
        headers=headers or {},
        cookies={},
        state={},
        app_state=None,
        domain_request=domain_request,
    )


def test_extract_uses_precedence_header_then_body_then_extra_body() -> None:
    extractor = DefaultClientSessionIdExtractor(config=AppConfig())
    context = _make_context(
        headers={"x-session-id": " header-id "},
        body_session_id="body-id",
        extra_body_session_id="extra-id",
    )

    extracted = extractor.extract_client_session_id(context)

    assert extracted == "header-id"


def test_extract_treats_whitespace_candidates_as_absent() -> None:
    extractor = DefaultClientSessionIdExtractor(config=AppConfig())
    context = _make_context(
        headers={"x-session-id": "   "},
        body_session_id="  ",
        extra_body_session_id="extra-id",
    )

    extracted = extractor.extract_client_session_id(context)

    assert extracted == "extra-id"


def test_extract_ignores_default_echo_header_for_identity() -> None:
    extractor = DefaultClientSessionIdExtractor(config=AppConfig())
    context = _make_context(headers={"x-b2bua-session-id": "echo-inbound"})

    extracted = extractor.extract_client_session_id(context)

    assert extracted is None


def test_extract_ignores_configured_echo_header_for_identity() -> None:
    config = AppConfig(session={"b2bua": {"echo_header_name": "x-custom-echo"}})
    extractor = DefaultClientSessionIdExtractor(config=config)
    context = _make_context(headers={"x-custom-echo": "echo-inbound"})

    extracted = extractor.extract_client_session_id(context)

    assert extracted is None


def test_extract_sets_conflict_diagnostic_when_candidates_differ() -> None:
    extractor = DefaultClientSessionIdExtractor(config=AppConfig())
    context = _make_context(
        headers={"x-session-id": "header-id"},
        body_session_id="body-id",
    )

    extracted = extractor.extract_client_session_id(context)

    assert extracted == "header-id"
    processing = context.ensure_processing_context().values
    assert processing["b2bua_client_session_id_conflict"] is True


def test_extract_stores_selected_client_session_as_metadata_only() -> None:
    extractor = DefaultClientSessionIdExtractor(config=AppConfig())
    context = _make_context(headers={"x-session-id": "client-id-1"})

    extracted = extractor.extract_client_session_id(context)

    assert extracted == "client-id-1"
    processing = context.ensure_processing_context().values
    assert processing["b2bua_client_session_id"] == "client-id-1"
    assert context.session_id is None
