"""Tests for mapping Responses protocol errors to HTTP (OpenAI-compatible envelope)."""

import json

from fastapi import FastAPI, status
from src.core.common.exceptions import (
    ResponsesPreviousResponseNotFoundError,
    ResponsesProtocolError,
    ResponsesProviderLimitationError,
    ResponsesValidationError,
)
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
    register_exception_handlers,
)


class TestResponsesProtocolExceptionAdapter:
    def test_maps_validation_error_to_nested_error_envelope(self) -> None:
        exc = ResponsesValidationError(
            "model is required",
            code="missing_required_parameter",
            param="model",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        http_exc = map_domain_exception_to_http_exception(exc)
        assert http_exc.status_code == 400
        detail_raw = http_exc.detail
        assert isinstance(detail_raw, dict)
        detail: dict[str, object] = detail_raw
        assert "error" in detail
        err = detail["error"]
        assert isinstance(err, dict)
        assert err["message"] == "model is required"
        assert err.get("code") == "missing_required_parameter"
        assert err.get("param") == "model"
        assert err.get("type") == "invalid_request_error"
        raw = json.dumps(detail)
        assert "missing_required_parameter" in raw

    def test_maps_previous_response_not_found(self) -> None:
        exc = ResponsesPreviousResponseNotFoundError("resp_missing")
        http_exc = map_domain_exception_to_http_exception(exc)
        assert http_exc.status_code == 400
        detail_raw = http_exc.detail
        assert isinstance(detail_raw, dict)
        err_obj = detail_raw.get("error")
        assert isinstance(err_obj, dict)
        assert err_obj.get("code") == "previous_response_not_found"
        assert "resp_missing" in str(err_obj.get("message"))

    def test_maps_provider_limitation(self) -> None:
        exc = ResponsesProviderLimitationError("include", "anthropic")
        http_exc = map_domain_exception_to_http_exception(exc)
        assert http_exc.status_code == 400
        detail_raw = http_exc.detail
        assert isinstance(detail_raw, dict)
        err_obj = detail_raw.get("error")
        assert isinstance(err_obj, dict)
        assert err_obj.get("code") == "provider_limitation"
        msg = str(err_obj.get("message"))
        assert "anthropic" in msg
        assert "include" in msg

    def test_base_protocol_error_respects_status_code(self) -> None:
        exc = ResponsesProtocolError(
            "x",
            code="custom",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
        http_exc = map_domain_exception_to_http_exception(exc)
        assert http_exc.status_code == 422


class TestResponsesProtocolExceptionRegistration:
    def test_registers_protocol_specific_handlers(self) -> None:
        app = FastAPI()

        register_exception_handlers(app)

        assert ResponsesProtocolError in app.exception_handlers
        assert ResponsesValidationError in app.exception_handlers
