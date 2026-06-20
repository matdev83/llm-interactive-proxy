import pytest
from src.core.app.stages.processor import ProcessorStage
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.di.container import ServiceCollection
from src.core.services.tool_progress_loop_guard import ToolProgressLoopGuard


@pytest.mark.asyncio
async def test_tool_progress_loop_guard_uses_session_config() -> None:
    config = AppConfig(
        session=SessionConfig(
            tool_progress_loop_guard_enabled=False,
            tool_progress_loop_max_consecutive_followups=4,
            tool_progress_loop_max_repeated_call_signature=5,
            tool_progress_loop_max_repeated_output=6,
            tool_progress_loop_max_counts_per_session=7,
            tool_progress_loop_max_cached_sessions=8,
        )
    )
    services = ServiceCollection()
    services.add_instance(AppConfig, config)

    await ProcessorStage().execute(services, config)
    provider = services.build_service_provider()

    guard = provider.get_required_service(ToolProgressLoopGuard)

    assert guard._enabled is False
    assert guard._max_consecutive_tool_followups == 4
    assert guard._max_repeated_tool_call_signature == 5
    assert guard._max_repeated_tool_output == 6
    assert guard._max_counts_per_session == 7
    assert guard._max_cached_sessions == 8


@pytest.mark.asyncio
async def test_tool_progress_loop_guard_wires_action_and_steering_message() -> None:
    config = AppConfig(
        session=SessionConfig(
            tool_progress_loop_action="steer_then_error",
            tool_progress_loop_steering_message="Custom steer message",
        )
    )
    services = ServiceCollection()
    services.add_instance(AppConfig, config)

    await ProcessorStage().execute(services, config)
    provider = services.build_service_provider()

    guard = provider.get_required_service(ToolProgressLoopGuard)

    assert guard._action_mode == "steer_then_error"
    assert guard._steering_message == "Custom steer message"
