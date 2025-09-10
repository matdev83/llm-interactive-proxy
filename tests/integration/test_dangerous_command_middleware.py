import json

import pytest
from src.core.domain.configuration.dangerous_command_config import (
    DEFAULT_DANGEROUS_COMMAND_CONFIG,
)
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.dangerous_command_service import DangerousCommandService
from src.core.services.tool_call_handlers.dangerous_command_handler import (
    DangerousCommandHandler,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,should_swallow", [(True, True), (False, False)])
async def test_dangerous_command_handler_integration(
    enabled: bool, should_swallow: bool
) -> None:
    """Integration-like test for DangerousCommandHandler behavior based on enable flag."""
    handler = DangerousCommandHandler(
        DangerousCommandService(DEFAULT_DANGEROUS_COMMAND_CONFIG), enabled=enabled
    )
    ctx = ToolCallContext(
        session_id="s",
        backend_name="openai",
        model_name="gpt-4",
        full_response="",
        tool_name="exec_command",
        tool_arguments=json.dumps({"command": "git clean -f"}),
    )

    can = await handler.can_handle(ctx)
    if enabled:
        assert can is True
        res = await handler.handle(ctx)
        assert res.should_swallow is True
        assert res.replacement_response
    else:
        assert can is False
