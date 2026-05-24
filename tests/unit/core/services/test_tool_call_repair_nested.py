import json

from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestToolCallRepairNested:
    def test_repair_tool_calls_xml_nested_command(self) -> None:
        """Test that execute_command with nested command tag is parsed correctly."""
        repair_service = ToolCallRepairService()
        content = """
        <execute_command>
            <command>./.venv/Scripts/python.exe -m pytest</command>
        </execute_command>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "execute_command"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["command"] == "./.venv/Scripts/python.exe -m pytest"

    def test_repair_tool_calls_xml_nested_command_with_newlines(self) -> None:
        """Test that execute_command with nested command tag and newlines is parsed correctly."""
        repair_service = ToolCallRepairService()
        content = "\n<execute_command>\n<command>./.venv/Scripts/python.exe -m pytest</command>\n</execute_command>\n"
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "execute_command"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["command"] == "./.venv/Scripts/python.exe -m pytest"

        # Verify that the snippet matches exactly for removal
        assert repaired.snippet in content
