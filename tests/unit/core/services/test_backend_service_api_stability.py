from __future__ import annotations

import inspect
from inspect import Parameter

from src.core.common.exceptions import BackendError as CommonBackendError
from src.core.interfaces.backend_service import IBackendService
from src.core.interfaces.backend_service_interface import (
    BackendError as ShimBackendError,
)
from src.core.services.backend_service import BackendService


def _assert_param(
    param: Parameter,
    *,
    name: str,
    kind: inspect._ParameterKind,
    default: object = Parameter.empty,
) -> None:
    assert param.name == name
    assert param.kind is kind
    assert param.default == default


class TestIBackendServiceSignatureStability:
    def test_interface_shape_is_stable(self) -> None:
        assert hasattr(IBackendService, "call_completion")
        assert hasattr(IBackendService, "validate_backend_and_model")
        assert hasattr(IBackendService, "chat_completions")
        assert hasattr(IBackendService, "get_backend")
        assert hasattr(IBackendService, "get_active_backends")

    def test_backend_error_reexport_is_canonical(self) -> None:
        assert ShimBackendError is CommonBackendError

    def test_call_completion_signature_is_stable(self) -> None:
        sig = inspect.signature(IBackendService.call_completion)
        params = list(sig.parameters.values())
        assert len(params) == 5
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="request", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(
            params[2],
            name="stream",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=False,
        )
        _assert_param(
            params[3],
            name="allow_failover",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=True,
        )
        _assert_param(
            params[4],
            name="context",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=None,
        )

    def test_validate_backend_and_model_signature_is_stable(self) -> None:
        sig = inspect.signature(IBackendService.validate_backend_and_model)
        params = list(sig.parameters.values())
        assert len(params) == 3
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="backend", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[2], name="model", kind=Parameter.POSITIONAL_OR_KEYWORD)

    def test_chat_completions_signature_is_stable(self) -> None:
        sig = inspect.signature(IBackendService.chat_completions)
        params = list(sig.parameters.values())
        assert len(params) == 3
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="request", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[2], name="kwargs", kind=Parameter.VAR_KEYWORD)

    def test_get_backend_signature_is_stable(self) -> None:
        sig = inspect.signature(IBackendService.get_backend)
        params = list(sig.parameters.values())
        assert len(params) == 2
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(
            params[1], name="backend_type", kind=Parameter.POSITIONAL_OR_KEYWORD
        )

    def test_get_active_backends_signature_is_stable(self) -> None:
        sig = inspect.signature(IBackendService.get_active_backends)
        params = list(sig.parameters.values())
        assert len(params) == 1
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)


class TestBackendServiceSignatureStability:
    def test_call_completion_signature_is_stable(self) -> None:
        sig = inspect.signature(BackendService.call_completion)
        params = list(sig.parameters.values())
        assert len(params) == 5
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="request", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(
            params[2],
            name="stream",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=False,
        )
        _assert_param(
            params[3],
            name="allow_failover",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=True,
        )
        _assert_param(
            params[4],
            name="context",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            default=None,
        )

    def test_validate_backend_and_model_signature_is_stable(self) -> None:
        sig = inspect.signature(BackendService.validate_backend_and_model)
        params = list(sig.parameters.values())
        assert len(params) == 3
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="backend", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[2], name="model", kind=Parameter.POSITIONAL_OR_KEYWORD)

    def test_chat_completions_signature_is_stable(self) -> None:
        sig = inspect.signature(BackendService.chat_completions)
        params = list(sig.parameters.values())
        assert len(params) == 3
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[1], name="request", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(params[2], name="kwargs", kind=Parameter.VAR_KEYWORD)

    def test_get_backend_signature_is_stable(self) -> None:
        sig = inspect.signature(BackendService.get_backend)
        params = list(sig.parameters.values())
        assert len(params) == 2
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
        _assert_param(
            params[1], name="backend_type", kind=Parameter.POSITIONAL_OR_KEYWORD
        )

    def test_get_active_backends_signature_is_stable(self) -> None:
        sig = inspect.signature(BackendService.get_active_backends)
        params = list(sig.parameters.values())
        assert len(params) == 1
        _assert_param(params[0], name="self", kind=Parameter.POSITIONAL_OR_KEYWORD)
