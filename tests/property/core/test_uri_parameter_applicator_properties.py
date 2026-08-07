"""Property-based tests for URIParameterApplicator.

Validates:
- Property 7: Parameter Precedence (Requirements 8.1, 8.2)
- Property 8: Parameter Type Coercion (Requirements 8.3)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
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


temperature_values = st.floats(
    min_value=0.0,
    max_value=2.0,
    allow_nan=False,
    allow_infinity=False,
)

top_p_values = st.floats(
    min_value=0.0,
    max_value=1.0,
    allow_nan=False,
    allow_infinity=False,
)

top_k_values = st.integers(min_value=1, max_value=512)


@st.composite
def top_k_representations(draw: st.DrawFn) -> tuple[int, object]:
    """Generate a valid integer top_k and a raw representation that should coerce."""
    value = draw(top_k_values)
    representation_kind = draw(
        st.sampled_from(["int", "float", "str_int", "str_float", "str_spaced"])
    )
    if representation_kind == "int":
        return value, value
    if representation_kind == "float":
        return value, float(value)
    if representation_kind == "str_int":
        return value, str(value)
    if representation_kind == "str_float":
        return value, f"{value}.0"
    return value, f"  {value}  "


class TestParameterPrecedenceProperty:
    """Property 7: Parameter Precedence (Requirements 8.1, 8.2)."""

    @given(
        config_temperature=temperature_values,
        header_temperature=temperature_values,
        uri_temperature=temperature_values,
        session_temperature=temperature_values,
        has_config=st.booleans(),
        has_header=st.booleans(),
        has_uri=st.booleans(),
        has_session=st.booleans(),
    )
    @settings(max_examples=50)
    def test_temperature_precedence_session_uri_header_config(
        self,
        config_temperature: float,
        header_temperature: float,
        uri_temperature: float,
        session_temperature: float,
        has_config: bool,
        has_header: bool,
        has_uri: bool,
        has_session: bool,
    ) -> None:
        """Session > URI > headers > config for conflicting temperature values."""
        if has_session and has_uri:
            assume(session_temperature != uri_temperature)

        backend_type = "test-backend"

        config = _make_config(
            backend_type,
            extra={"temperature": config_temperature} if has_config else {},
        )

        request_extra_body: dict[str, object] = {}
        if has_header:
            request_extra_body["temperature"] = header_temperature

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body=request_extra_body or None,
        )

        uri_params: dict[str, object] = {"top_p": "0.5"}  # ensure non-empty
        if has_uri:
            uri_params["temperature"] = str(uri_temperature)

        session = None
        if has_session:
            session = MagicMock()
            session.state = SimpleNamespace(planning_phase_config=None)
            session.get_reasoning_mode = MagicMock(
                return_value=SimpleNamespace(temperature=session_temperature)
            )

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=session,
        )

        expected: float | None
        if has_session:
            expected = session_temperature
        elif has_uri:
            expected = float(uri_temperature)
        elif has_header:
            expected = header_temperature
        elif has_config:
            expected = config_temperature
        else:
            expected = None

        assert result.temperature == expected


class TestParameterTypeCoercionProperty:
    """Property 8: Parameter Type Coercion (Requirements 8.3)."""

    @given(
        temperature=temperature_values,
        top_p=top_p_values,
        top_k=top_k_representations(),
        effort=st.sampled_from(["low", "medium", "high"]),
    )
    @settings(max_examples=50)
    def test_supported_parameters_coerced_to_expected_types(
        self,
        temperature: float,
        top_p: float,
        top_k: tuple[int, object],
        effort: str,
    ) -> None:
        """Coercion produces canonical types in request fields and extra_body."""
        backend_type = "test-backend"
        config = _make_config(backend_type, extra={})

        expected_top_k, raw_top_k = top_k

        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="hi")],
            extra_body={
                "top_k": raw_top_k,
                "reasoning_effort": effort,
            },
        )

        uri_params = {
            "temperature": str(temperature),
            "top_p": str(top_p),
        }

        result = URIParameterApplicator(config=config).apply(
            request=request,
            uri_params=uri_params,
            backend_type=backend_type,
            session=None,
        )

        assert isinstance(result.temperature, float)
        assert result.temperature == pytest.approx(float(temperature))

        assert isinstance(result.top_p, float)
        assert result.top_p == pytest.approx(float(top_p))

        assert isinstance(result.top_k, int)
        assert result.top_k == expected_top_k

        assert isinstance(result.reasoning_effort, str)
        assert result.reasoning_effort == effort

        assert result.extra_body is not None
        assert isinstance(result.extra_body.get("temperature"), float)
        assert isinstance(result.extra_body.get("top_p"), float)
        assert isinstance(result.extra_body.get("top_k"), int)
        assert isinstance(result.extra_body.get("reasoning_effort"), str)
