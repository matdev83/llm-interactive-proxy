"""Unit tests for URIParameterApplicator."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel
from pydantic.types import JsonValue
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.uri_parameter_applicator import URIParameterApplicator


def _make_config(backend_type: str, extra: dict) -> AppConfig:
    return AppConfig(
        backends=BackendSettings(
            default_backend="openai",
            **{backend_type: BackendConfig(extra=extra)},
        )
    )


class TestURIParameterApplicatorPrecedence:
    """Tests for parameter source precedence."""

    def test_session_overrides_uri(self) -> None:
        """Session overrides should win over URI parameters for conflicts."""
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"temperature": 0.9})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={"temperature": 0.7},
        )
        uri_params = {"temperature": "0.5"}

        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(
            return_value=SimpleNamespace(temperature=0.2)
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=session,
        )

        assert result.temperature == pytest.approx(0.2)

    def test_uri_overrides_header_and_config_when_no_session(self) -> None:
        """URI should override header and config in absence of session overrides."""
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"temperature": 0.9})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={"temperature": 0.7},
        )
        uri_params = {"temperature": "0.5"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.5)

    def test_edit_precision_promotes_request_sampling_to_session_precedence(
        self,
    ) -> None:
        """Edit-precision mode should treat request sampling as session overrides."""
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.1,
            extra_body={"_edit_precision_mode": True},
        )
        uri_params = {"temperature": "0.9"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.1)

    def test_explicit_request_field_overrides_uri_defaults(self) -> None:
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"temperature": 0.9})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.7,
            extra_body={"temperature": 0.3},
        )
        uri_params = {"temperature": "0.5"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.7)

    def test_connector_forced_overrides_uri_and_request(self) -> None:
        backend_type = "test-backend"
        config = _make_config(
            backend_type,
            extra={"temperature": 0.9, "forced_temperature": 0.1},
        )

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.6,
            extra_body={"temperature": 0.4},
        )
        uri_params = {"temperature": "0.5"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.1)


class TestURIParameterApplicatorCoercion:
    """Tests for type coercion behavior."""

    def test_rejects_non_integer_top_k_and_falls_back(self) -> None:
        """Non-integer top_k values should be ignored."""
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"top_k": 8})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={"top_k": "10.5"},
        )
        # Ensure applicator runs, but do not provide top_k via URI
        uri_params = {"temperature": "0.5"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.top_k == 8
        assert result.extra_body is not None
        assert result.extra_body.get("top_k") == 8


class TestEquivalenceWithBackendService:
    """Ensure URIParameterApplicator matches BackendService._apply_uri_parameters."""

    def test_matches_backend_service_on_simple_fixture(self) -> None:
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"temperature": 0.9})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={"temperature": 0.7},
        )
        uri_params = {"temperature": "0.5"}

        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(
            return_value=SimpleNamespace(temperature=0.2)
        )

        # Create the applicator and compare results
        applicator = URIParameterApplicator(config=config)
        applicator_result = applicator.apply(request, uri_params, backend_type, session)

        # The applicator should apply session temperature (0.2) since session > URI > header > config
        assert applicator_result.temperature == 0.2


class TestURIParameterApplicatorReasoningEffort:
    """URI reasoning_effort handling, including xhigh downgrade behavior."""

    def test_uri_reasoning_effort_overrides_defaulted_sdk_request_field(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra={})

        class SDKStyleRequest(BaseModel):
            model: str
            messages: list[ChatMessage]
            extra_body: dict[str, object] | None = None
            temperature: float | None = None
            top_p: float | None = None
            top_k: int | None = None
            reasoning_effort: str = "medium"

        request = SDKStyleRequest(
            model="openai-codex:gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert "reasoning_effort" not in request.model_fields_set
        uri_params: dict[str, JsonValue] = {"reasoning_effort": "high"}

        result = URIParameterApplicator(config=config).apply(
            request=cast(Any, request),
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "high"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "high"

    def test_uri_xhigh_applied_to_request_for_codex(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai-codex:gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="hi")],
        )
        uri_params = {"reasoning_effort": "xhigh"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "xhigh"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "xhigh"

    def test_uri_xhigh_downgraded_to_high_for_non_codex_backend(self) -> None:
        backend_type = "openai"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai:gpt-4.1",
            messages=[ChatMessage(role="user", content="hi")],
        )
        uri_params = {"reasoning_effort": "xhigh"}

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "high"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "high"
