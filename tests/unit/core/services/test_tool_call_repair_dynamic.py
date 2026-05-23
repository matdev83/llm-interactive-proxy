import json

import pytest
from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestToolCallRepairServiceDynamic:
    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_repair_tool_calls_dynamic_tool(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <custom_tool>
            <arg>value</arg>
        </custom_tool>
        """
        repaired = repair_service.repair_tool_calls(
            content, allowed_tools=["custom_tool"]
        )
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "custom_tool"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["arg"] == "value"

    def test_repair_tool_calls_dynamic_tool_priority(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <wrapper>
            <my_tool>
                <arg>value</arg>
            </my_tool>
        </wrapper>
        """
        repaired = repair_service.repair_tool_calls(content, allowed_tools=["my_tool"])
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "my_tool"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["arg"] == "value"

    def test_repair_tool_calls_fallback_to_defaults(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <read_file>
            <path>test.txt</path>
        </read_file>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "read_file"
