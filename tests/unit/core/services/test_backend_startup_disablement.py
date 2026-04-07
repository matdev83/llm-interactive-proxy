from typing import cast

import pytest
from src.core.config.app_config import AppConfig
from src.core.services.backend_startup_disablement import (
    compute_backends_to_disable_at_startup,
)


def test_disables_kimi_code_when_no_credentials_present() -> None:
    config = AppConfig(backends={"default_backend": "openai"})
    disabled = compute_backends_to_disable_at_startup(
        config=config,
        registered_backends=["kimi-code"],
        env={},
    )
    assert "kimi-code" in disabled
    assert "KIMI_API_KEY" in disabled["kimi-code"]


def test_does_not_disable_when_base_backend_has_key() -> None:
    config = AppConfig(backends={"kimi-code": {"api_key": "val"}})
    disabled = compute_backends_to_disable_at_startup(
        config=config,
        registered_backends=["kimi-code"],
        env={},
    )
    assert "kimi-code" not in disabled


def test_does_not_disable_when_any_instance_has_key() -> None:
    config = AppConfig(backends={"kimi-code.1": {"api_key": "val"}})
    disabled = compute_backends_to_disable_at_startup(
        config=config,
        registered_backends=["kimi-code"],
        env={},
    )
    assert "kimi-code" not in disabled


def test_does_not_disable_when_env_var_is_present_for_env_fallback_backend() -> None:
    # zai-coding-plan reads ZAI_CODING_PLAN_API_KEY directly in the connector.
    config = AppConfig(backends={"default_backend": "openrouter"})
    disabled = compute_backends_to_disable_at_startup(
        config=config,
        registered_backends=["zai-coding-plan"],
        env={"ZAI_CODING_PLAN_API_KEY": "val"},
    )
    assert "zai-coding-plan" not in disabled


def test_openai_responses_uses_openai_credentials() -> None:
    config = AppConfig(backends={"openai": {"api_key": "val"}})
    disabled = compute_backends_to_disable_at_startup(
        config=config,
        registered_backends=["openai-responses"],
        env={},
    )
    assert "openai-responses" not in disabled


@pytest.mark.asyncio
async def test_availability_checker_raises_service_unavailable_for_disabled_backend() -> (
    None
):
    from src.core.common.exceptions import ServiceUnavailableError
    from src.core.interfaces.backend_lifecycle_manager_interface import (
        IBackendLifecycleManager,
    )
    from src.core.services.backend_completion_flow.availability_checker import (
        BackendAvailabilityChecker,
    )
    from src.core.services.backend_lifecycle_types import DisabledBackendInfo

    class _StubLifecycle:
        def get_disabled_backends(self):
            return {"kimi-code": DisabledBackendInfo(reason="no key", timestamp=0.0)}

    checker = BackendAvailabilityChecker(
        backend_lifecycle_manager=cast(IBackendLifecycleManager, _StubLifecycle()),
        resilience_coordinator=None,
        failover_routes={},
    )

    with pytest.raises(ServiceUnavailableError):
        await checker.check_backend_availability(
            backend_type="kimi-code",
            effective_model="kimi/kimi-for-coding",
            allow_failover=False,
            context=None,
        )
