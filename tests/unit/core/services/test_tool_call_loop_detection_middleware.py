from __future__ import annotations

import asyncio

import pytest
from src.core.domain.configuration.loop_detection_config import LoopDetectionConfiguration
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_call_loop_middleware import ToolCallLoopDetectionMiddleware
from src.tool_call_loop.config import ToolLoopMode


def _make_response(tool_name: str, arguments: str = "{}") -> ProcessedResponse:
    return ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": tool_name,
                                    "arguments": arguments,
                                }
                            }
                        ]
                    }
                }
            ]
        },
        metadata={},
    )


@pytest.mark.asyncio
async def test_tool_call_loop_detection_isolates_sessions() -> None:
    middleware = ToolCallLoopDetectionMiddleware()
    config = LoopDetectionConfiguration(
        tool_loop_detection_enabled=True,
        tool_loop_max_repeats=4,
        tool_loop_ttl_seconds=120,
        tool_loop_mode=ToolLoopMode.BREAK,
    )

    async def run_session(session_id: str, tool_name: str) -> None:
        response = _make_response(tool_name)
        await middleware.process(
            response=response,
            session_id=session_id,
            context={"config": config},
            is_streaming=False,
        )

    await asyncio.gather(
        run_session("session-alpha", "alpha_tool"),
        run_session("session-beta", "beta_tool"),
    )

    assert set(middleware._session_trackers.keys()) == {"session-alpha", "session-beta"}

    alpha_tracker = middleware._session_trackers["session-alpha"]
    beta_tracker = middleware._session_trackers["session-beta"]

    assert [sig.tool_name for sig in alpha_tracker.signatures] == ["alpha_tool"]
    assert [sig.tool_name for sig in beta_tracker.signatures] == ["beta_tool"]

    # Subsequent calls for each session should reuse their own tracker
    await asyncio.gather(
        run_session("session-alpha", "alpha_tool"),
        run_session("session-beta", "beta_tool"),
    )

    assert len(alpha_tracker.signatures) == 2
    assert len(beta_tracker.signatures) == 2
