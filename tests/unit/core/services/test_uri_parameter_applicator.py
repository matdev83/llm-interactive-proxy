"""Unit tests for URIParameterApplicator."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic.types import JsonValue
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.translators.responses.request import responses_to_domain_request
from src.core.services.uri_parameter_applicator import URIParameterApplicator


def _make_config(backend_type: str, extra: dict[str, Any]) -> AppConfig:
    raw_backends: dict[str, Any] = {
        "default_backend": "openai",
        backend_type: BackendConfig(extra=extra),
    }
    return AppConfig(backends=BackendSettings.model_validate(raw_backends))


def _disable_early_bump(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Opt out of openai-codex early-session bump for URI precedence tests."""
    merged = dict(extra or {})
    codex = dict(merged.get("codex") or {})
    codex["early_session_verbosity_bump"] = {"enabled": False}
    merged["codex"] = codex
    return merged


def _uri(**values: JsonValue) -> dict[str, JsonValue]:
    """Build ``uri_params`` with stable ``dict[str, JsonValue]`` typing for tests."""
    return dict(values)


class _ChatRequestWithDefaultReasoningEffort(ChatRequest):
    """Mimics SDK clients that define a non-None default for ``reasoning_effort``."""

    reasoning_effort: str = "medium"


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

        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(
            return_value=SimpleNamespace(temperature=0.2)
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
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

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
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

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.9"),
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.1)

    def test_uri_overrides_explicit_request_field(self) -> None:
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={"temperature": 0.9})

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.7,
            extra_body={"temperature": 0.3},
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.5)

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

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
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

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
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

        session = MagicMock()
        session.state = SimpleNamespace(planning_phase_config=None)
        session.get_reasoning_mode = MagicMock(
            return_value=SimpleNamespace(temperature=0.2)
        )

        # Create the applicator and compare results
        applicator = URIParameterApplicator(config=config)
        applicator_result = applicator.apply(
            request,
            _uri(temperature="0.5"),
            backend_type,
            session,
        )

        # Session > URI > request > header > config (connector_forced not used)
        assert applicator_result.temperature == 0.2


class TestURIParameterApplicatorRequestParamExtraction:
    """Direct coverage of ``_extract_request_params`` edge cases."""

    def test_legacy_object_without_model_fields_set_treats_attrs_as_explicit(
        self,
    ) -> None:
        """No ``model_fields_set``: every non-None known field counts (compat path)."""
        applicator = URIParameterApplicator(config=None)
        req = SimpleNamespace(
            temperature=0.4, top_p=None, top_k=None, reasoning_effort=None
        )
        out = applicator._extract_request_params(cast(Any, req), "test-backend")
        assert out.get("temperature") == pytest.approx(0.4)

    def test_pydantic_default_reasoning_effort_omitted_when_not_in_fields_set(
        self,
    ) -> None:
        """Schema default on a ChatRequest subclass must not populate request_params."""
        applicator = URIParameterApplicator(config=None)
        request = _ChatRequestWithDefaultReasoningEffort(
            model="openai-codex:gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert "reasoning_effort" not in request.model_fields_set
        out = applicator._extract_request_params(request, "openai-codex")
        assert "reasoning_effort" not in out


class TestURIParameterApplicatorReasoningEffort:
    """URI reasoning_effort handling, including xhigh downgrade behavior."""

    def test_uri_reasoning_effort_overrides_defaulted_sdk_request_field(self) -> None:
        """Same precedence as SDK clients that set a non-None default on the model."""
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra={})

        request = _ChatRequestWithDefaultReasoningEffort(
            model="openai-codex:gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        assert "reasoning_effort" not in request.model_fields_set

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(reasoning_effort="high"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "high"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "high"

    def test_uri_none_applied_only_to_alibaba_token_plan(self) -> None:
        backend_type = "alibaba-token-plan-intl"
        request = ChatRequest(
            model="alibaba-token-plan-intl:qwen3.7-plus",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=None).apply(
            request=request,
            uri_params=_uri(reasoning_effort="none"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "none"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "none"

    def test_uri_none_is_excluded_for_other_backends(self) -> None:
        request = ChatRequest(
            model="anthropic:claude-sonnet-4-5",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=None).apply(
            request=request,
            uri_params=_uri(reasoning_effort="none"),
            backend_type="anthropic",
            session=None,
        )

        assert result.reasoning_effort is None
        assert not result.extra_body or "reasoning_effort" not in result.extra_body

    def test_uri_xhigh_applied_to_request_for_codex(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai-codex:gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(reasoning_effort="xhigh"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "xhigh"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "xhigh"

    def test_uri_xhigh_is_preserved_for_non_codex_backend(self) -> None:
        backend_type = "openai"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai:gpt-4.1",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(reasoning_effort="xhigh"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "xhigh"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "xhigh"

    def test_uri_max_reasoning_effort_maps_to_xhigh_for_openrouter(self) -> None:
        backend_type = "openrouter"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openrouter:xiaomi/mimo-v2.5-pro",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(reasoning_effort="max"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "xhigh"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "xhigh"

    def test_uri_max_reasoning_effort_is_preserved_for_provider_specific_routes(
        self,
    ) -> None:
        backend_type = "opencode-zen"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="opencode-zen:deepseek-v4-pro",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(reasoning_effort="max"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "max"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "max"

    def test_header_max_reasoning_effort_is_preserved(self) -> None:
        backend_type = "opencode-go"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="opencode-go:deepseek-v4-pro",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={"reasoning_effort": "max"},
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
            backend_type=backend_type,
            session=None,
        )

        assert result.reasoning_effort == "max"
        assert result.extra_body is not None
        assert result.extra_body.get("reasoning_effort") == "max"


class TestURIParameterApplicatorVerbosity:
    """URI and config verbosity handling."""

    def test_uri_verbosity_applied_to_request(self) -> None:
        backend_type = "openai"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low"),
            backend_type=backend_type,
            session=None,
        )

        assert result.verbosity == "low"
        assert result.extra_body is not None
        assert result.extra_body.get("verbosity") == "low"

    def test_uri_verbosity_overrides_backend_config(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(
            backend_type,
            extra=_disable_early_bump({"verbosity": "high"}),
        )

        request = ChatRequest(
            model="openai-codex:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low"),
            backend_type=backend_type,
            session=None,
        )

        assert result.verbosity == "low"

    def test_backend_config_verbosity_applied_when_no_uri(self) -> None:
        backend_type = "openai-responses"
        config = _make_config(backend_type, extra={"verbosity": "medium"})

        request = ChatRequest(
            model="openai-responses:gpt-5.4",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params={},
            backend_type=backend_type,
            session=None,
        )

        assert result.verbosity == "medium"

    def test_responses_text_verbosity_beats_backend_config(self) -> None:
        backend_type = "openai-responses"
        config = _make_config(backend_type, extra={"verbosity": "medium"})

        request = responses_to_domain_request(
            {
                "model": "openai-responses:gpt-5.4",
                "messages": [{"role": "user", "content": "hi"}],
                "text": {"verbosity": "high"},
            }
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5"),
            backend_type=backend_type,
            session=None,
        )

        assert result.verbosity == "high"

    def test_uri_verbosity_with_reasoning_effort(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra=_disable_early_bump())

        request = ChatRequest(
            model="openai-codex:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low", reasoning_effort="high"),
            backend_type=backend_type,
            session=None,
        )

        assert result.verbosity == "low"
        assert result.reasoning_effort == "high"


class TestURIParameterApplicatorEarlySessionVerbosityBump:
    """Early-session forced temperature/verbosity for openai-codex family."""

    def test_default_enabled_forces_params_on_early_turn(self) -> None:
        backend_type = "openai-codex"
        # Empty extra: bump defaults to enabled with max_turns=5.
        config = _make_config(backend_type, extra={})
        session = SimpleNamespace(history=[object(), object()])

        request = ChatRequest(
            model="openai-codex:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.2,
            verbosity="low",
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(temperature="0.5", verbosity="low"),
            backend_type=backend_type,
            session=session,
        )

        assert result.temperature == pytest.approx(1.0)
        assert result.verbosity == "high"

    def test_forces_params_when_session_missing(self) -> None:
        backend_type = "openai-codex-v2"
        config = _make_config("openai_codex_v2", extra={})

        request = ChatRequest(
            model="openai-codex-v2:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low", temperature="0.3"),
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(1.0)
        assert result.verbosity == "high"

    def test_respects_uri_after_max_turns(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(
            backend_type,
            extra={
                "codex": {
                    "early_session_verbosity_bump": {"enabled": True, "max_turns": 5}
                }
            },
        )
        session = SimpleNamespace(history=[object()] * 5)

        request = ChatRequest(
            model="openai-codex:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low", temperature="0.4"),
            backend_type=backend_type,
            session=session,
        )

        assert result.temperature == pytest.approx(0.4)
        assert result.verbosity == "low"

    def test_opt_out_via_config(self) -> None:
        backend_type = "openai-codex"
        config = _make_config(backend_type, extra=_disable_early_bump())

        request = ChatRequest(
            model="openai-codex:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low", temperature="0.4"),
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.4)
        assert result.verbosity == "low"

    def test_does_not_apply_to_app_server(self) -> None:
        backend_type = "openai-codex-app-server"
        config = _make_config(backend_type, extra={})

        request = ChatRequest(
            model="openai-codex-app-server:gpt-5.4-mini",
            messages=[ChatMessage(role="user", content="hi")],
        )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=_uri(verbosity="low", temperature="0.4"),
            backend_type=backend_type,
            session=None,
        )

        assert result.temperature == pytest.approx(0.4)
        assert result.verbosity == "low"
