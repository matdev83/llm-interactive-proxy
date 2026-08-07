from src.core.services.application_state_service import ApplicationStateService


def test_feature_flags_default_false() -> None:
    svc = ApplicationStateService()
    assert svc.get_use_failover_strategy() is False
    assert svc.get_use_streaming_pipeline() is False


def test_feature_flags_set_and_get() -> None:
    svc = ApplicationStateService()
    svc.set_use_failover_strategy(True)
    svc.set_use_streaming_pipeline(True)
    assert svc.get_use_failover_strategy() is True
    assert svc.get_use_streaming_pipeline() is True


def test_feature_flags_state_provider_bridge() -> None:
    class Provider:
        pass

    provider = Provider()
    svc = ApplicationStateService(provider)
    # reflect through provider attributes
    svc.set_use_failover_strategy(True)
    svc.set_use_streaming_pipeline(False)
    assert getattr(provider, "PROXY_USE_FAILOVER_STRATEGY", None) is True
    assert getattr(provider, "PROXY_USE_STREAMING_PIPELINE", None) is False
