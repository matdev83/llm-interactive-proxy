"""Regression test to verify ToolCallRepairService._tool_call_buffers is dead code.

This test verifies that _tool_call_buffers attribute doesn't exist or is never used,
confirming it's dead code that was removed or never implemented.
"""

from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestToolCallRepairServiceBuffersDeadCodeRegression:
    """Regression tests to verify _tool_call_buffers is dead code."""

    def test_tool_call_buffers_does_not_exist(self) -> None:
        """Test that _tool_call_buffers attribute doesn't exist."""
        service = ToolCallRepairService()

        # Verify _tool_call_buffers doesn't exist
        assert not hasattr(service, "_tool_call_buffers"), (
            "_tool_call_buffers should not exist. "
            "If it exists, it's dead code and should be removed."
        )

    def test_repair_operations_dont_create_buffers(self) -> None:
        """Test that repair operations don't create or use buffers."""
        service = ToolCallRepairService()

        # Perform various repair operations
        result1 = service.repair_tool_calls(
            '{"function_call": {"name": "test", "arguments": "{}"}}'
        )
        result2 = service.repair_tool_calls("<test_tool>content</test_tool>")
        result3 = service.repair_tool_calls_in_messages(
            [{"role": "assistant", "content": "<test>args</test>"}]
        )

        # Verify operations completed
        assert (
            result1 is not None or result2 is not None or len(result3) > 0
        ), "Repair operations should complete"

        # Verify _tool_call_buffers still doesn't exist
        assert not hasattr(service, "_tool_call_buffers"), (
            "_tool_call_buffers should not exist after repair operations. "
            "If it exists, it's dead code and should be removed."
        )
