import asyncio
import json

import pytest
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.services.tool_text_renderer import (
    OverrideRenderer,
    render_tool_call,
    reset_renderer_registry,
)


@pytest.mark.asyncio
async def test_override_is_session_isolated() -> None:
    """Ensure renderer overrides do not leak across concurrent sessions."""
    reset_renderer_registry()
    tool_call = ToolCall(
        id="call-1",
        function=FunctionCall(
            name="shell",
            arguments=json.dumps({"command": ["echo", "hello"]}),
        ),
    )

    start_override = asyncio.Event()
    release_override = asyncio.Event()

    async def session_with_override() -> str | None:
        with OverrideRenderer("markdown"):
            start_override.set()
            await release_override.wait()
            return render_tool_call(tool_call)

    async def concurrent_session() -> str | None:
        await start_override.wait()
        result = render_tool_call(tool_call)
        release_override.set()
        return result

    override_result, default_result = await asyncio.gather(
        session_with_override(),
        concurrent_session(),
    )

    assert override_result is not None and "```bash" in override_result
    assert default_result is None
    assert render_tool_call(tool_call) is None
