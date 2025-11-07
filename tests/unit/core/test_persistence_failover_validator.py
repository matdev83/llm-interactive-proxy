from __future__ import annotations

import gc
import warnings
from typing import Any, TypeVar
from unittest.mock import AsyncMock

import pytest
from src.core.persistence import ServiceProviderFailoverRouteValidator

_T = TypeVar("_T")


class _DummyProvider:
    def __init__(self, service: Any):
        self._service = service

    def get_required_service(self, _service_type: type[_T]) -> _T:
        return self._service


def _strict_supplier() -> bool:
    return False


def test_validator_runs_backend_validation_when_loop_not_running() -> None:
    backend_service = type("BackendService", (), {})()
    backend_service.validate_backend_and_model = AsyncMock(return_value=(True, None))

    validator = ServiceProviderFailoverRouteValidator(
        _DummyProvider(backend_service), _strict_supplier
    )

    result = validator.validate("backend", "model")

    backend_service.validate_backend_and_model.assert_awaited_once()
    assert result.is_valid is True
    assert result.warning is None


@pytest.mark.asyncio
async def test_validator_does_not_leak_coroutines_when_loop_running() -> None:
    backend_service = type("BackendService", (), {})()
    backend_service.validate_backend_and_model = AsyncMock(return_value=(True, None))

    validator = ServiceProviderFailoverRouteValidator(
        _DummyProvider(backend_service), _strict_supplier
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        result = validator.validate("backend", "model")
        gc.collect()

    assert result.is_valid is True
    assert result.warning is not None
    backend_service.validate_backend_and_model.assert_not_called()
    assert not any("was never awaited" in str(w.message) for w in caught)
