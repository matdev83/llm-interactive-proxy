"""Integration tests for MCP bridge functionality in Codex-KiloCode compatibility layer."""

from __future__ import annotations

import pytest
from src.connectors._openai_codex_kilo_tool_translator import (
    KiloToolTranslator,
    TranslationError,
)
from src.core.services.universal_mcp_client import UniversalMCPClient
from src.core.services.universal_tool_executor import UniversalToolExecutor


class MockMCPServer:
    """Mock MCP server for testing."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.tools = {}
        self.resources = {}
        self.call_history = []

    def register_tool(self, tool_name: str, handler):
        """Register a tool handler."""
        self.tools[tool_name] = handler

    def register_resource(self, uri: str, content: str):
        """Register a resource."""
        self.resources[uri] = content

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool."""
        self.call_history.append({"tool": tool_name, "arguments": arguments})
        if tool_name in self.tools:
            return await self.tools[tool_name](arguments)
        return {"content": f"Tool {tool_name} not found", "isError": True}

    async def read_resource(self, uri: str) -> dict:
        """Read a resource."""
        if uri in self.resources:
            return {
                "content": self.resources[uri],
                "uri": uri,
                "mimeType": "text/plain",
            }
        return {"content": f"Resource {uri} not found", "isError": True}


@pytest.fixture
def mock_mcp_server():
    """Create a mock MCP server."""
    server = MockMCPServer("test-server")

    # Register some test tools
    async def patch_file_handler(args):
        diff = args.get("diff", "")
        return {
            "content": f"Applied patch: {diff[:50]}...",
            "isError": False,
        }

    async def custom_tool_handler(args):
        return {
            "content": f"Custom tool executed with args: {args}",
            "isError": False,
        }

    server.register_tool("patch_file", patch_file_handler)
    server.register_tool("custom_tool", custom_tool_handler)

    # Register some test resources
    server.register_resource(
        "file://test/resource.txt", "This is test resource content"
    )

    return server


@pytest.fixture
def mcp_client(mock_mcp_server):
    """Create an MCP client with mock server."""
    client = UniversalMCPClient()

    # Manually set up the mock server connection
    client._connected_servers["test-server"] = {
        "config": {},
        "status": "connected",
        "capabilities": {},
        "mock_server": mock_mcp_server,
    }

    # Register tools
    from src.core.services.universal_mcp_client import MCPToolDefinition

    patch_tool = MCPToolDefinition(
        name="patch_file",
        description="Apply a patch to a file",
        input_schema={
            "type": "object",
            "properties": {
                "diff": {"type": "string", "description": "Diff content"},
                "path": {"type": "string", "description": "File path"},
            },
            "required": ["diff"],
        },
    )

    custom_tool = MCPToolDefinition(
        name="custom_tool",
        description="A custom MCP tool",
        input_schema={
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
                "param2": {"type": "string"},
            },
        },
    )

    client._discovered_tools["patch_file"] = patch_tool
    client._discovered_tools["custom_tool"] = custom_tool
    client._tool_to_server_map["patch_file"] = "test-server"
    client._tool_to_server_map["custom_tool"] = "test-server"

    # Override execute_tool to use mock server
    original_execute = client.execute_tool

    async def mock_execute(tool_name: str, arguments: dict):
        server_name = client._tool_to_server_map.get(tool_name)
        if server_name and server_name in client._connected_servers:
            mock_server = client._connected_servers[server_name].get("mock_server")
            if mock_server:
                result = await mock_server.call_tool(tool_name, arguments)
                return {
                    "output": result.get("content", ""),
                    "exit_code": 0 if not result.get("isError", False) else 1,
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "mcp_result": result,
                }
        return await original_execute(tool_name, arguments)

    client.execute_tool = mock_execute

    # Override read_resource to use mock server
    async def mock_read_resource(uri: str):
        # Try to find a server that has this resource
        for _server_name, server_info in client._connected_servers.items():
            mock_server = server_info.get("mock_server")
            if mock_server:
                return await mock_server.read_resource(uri)
        return {"content": f"Resource {uri} not found", "isError": True}

    client.read_resource = mock_read_resource

    return client


@pytest.fixture
def tool_executor(mcp_client):
    """Create a tool executor with MCP client."""
    executor = UniversalToolExecutor(result_format="kilo_standard")
    executor.mcp_client = mcp_client
    return executor


@pytest.fixture
def translator(tool_executor):
    """Create a tool translator."""

    # Create a mock connector
    class MockConnector:
        def _get_universal_executor(self):
            return tool_executor

    connector = MockConnector()
    return KiloToolTranslator(connector)


class TestAccessMCPResourceTranslation:
    """Test translation and execution of <access_mcp_resource> tags."""

    @pytest.mark.asyncio
    async def test_translate_access_mcp_resource(self, translator):
        """Test translating access_mcp_resource to proxy marker."""
        xml = '<access_mcp_resource uri="file://test/resource.txt" />'

        result = await translator.translate_tool_invocation(xml)

        assert result is not None
        tool_name, arguments = result
        assert tool_name == "__proxy_access_mcp_resource"
        assert arguments["uri"] == "file://test/resource.txt"

    @pytest.mark.asyncio
    async def test_translate_access_mcp_resource_with_nested_uri(self, translator):
        """Test translating access_mcp_resource with nested URI tag."""
        xml = """<access_mcp_resource>
            <uri>file://test/resource.txt</uri>
        </access_mcp_resource>"""

        result = await translator.translate_tool_invocation(xml)

        assert result is not None
        tool_name, arguments = result
        assert tool_name == "__proxy_access_mcp_resource"
        assert arguments["uri"] == "file://test/resource.txt"

    @pytest.mark.asyncio
    async def test_translate_access_mcp_resource_missing_uri_raises_error(
        self, translator
    ):
        """Test that access_mcp_resource without URI raises error."""
        xml = "<access_mcp_resource></access_mcp_resource>"

        with pytest.raises(TranslationError) as exc_info:
            await translator.translate_tool_invocation(xml)

        # XML parsing error is caught first, so we get COMPAT_E002
        assert exc_info.value.error_code == "COMPAT_E002"
        assert "uri" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_access_mcp_resource(self, tool_executor):
        """Test executing access_mcp_resource."""
        result = await tool_executor.execute_tool(
            "__proxy_access_mcp_resource", {"uri": "file://test/resource.txt"}
        )

        assert result["exit_code"] == 0
        assert "test resource content" in result["output"].lower()
        assert "[access_mcp_resource] Result:" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_access_mcp_resource_not_found(self, tool_executor):
        """Test executing access_mcp_resource with non-existent resource."""
        result = await tool_executor.execute_tool(
            "__proxy_access_mcp_resource", {"uri": "file://nonexistent/resource.txt"}
        )

        # The mock server returns a placeholder response for non-existent resources
        # In a real implementation, this would return an error
        assert result["exit_code"] == 0
        assert "not found" in result["output"].lower()


class TestGenericMCPToolForwarding:
    """Test generic MCP tool forwarding via <use_mcp_tool>."""

    @pytest.mark.asyncio
    async def test_translate_use_mcp_tool_generic(self, translator):
        """Test translating generic use_mcp_tool."""
        xml = """<use_mcp_tool name="custom_tool">
            <arguments>
                <param1>value1</param1>
                <param2>value2</param2>
            </arguments>
        </use_mcp_tool>"""

        result = await translator.translate_tool_invocation(xml)

        assert result is not None
        tool_name, arguments = result
        assert tool_name == "__proxy_use_mcp_tool"
        assert arguments["tool_name"] == "custom_tool"
        assert arguments["tool_arguments"]["param1"] == "value1"
        assert arguments["tool_arguments"]["param2"] == "value2"

    @pytest.mark.asyncio
    async def test_execute_generic_mcp_tool(self, tool_executor, mock_mcp_server):
        """Test executing generic MCP tool."""
        result = await tool_executor.execute_tool(
            "__proxy_use_mcp_tool",
            {
                "tool_name": "custom_tool",
                "tool_arguments": {"param1": "value1", "param2": "value2"},
            },
        )

        assert result["exit_code"] == 0
        assert "custom tool executed" in result["output"].lower()
        assert "[custom_tool] Result:" in result["output"]

        # Verify the tool was called with correct arguments
        assert len(mock_mcp_server.call_history) == 1
        call = mock_mcp_server.call_history[0]
        assert call["tool"] == "custom_tool"
        assert call["arguments"]["param1"] == "value1"

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_not_available(self, tool_executor):
        """Test executing unavailable MCP tool returns error."""
        result = await tool_executor.execute_tool(
            "__proxy_use_mcp_tool",
            {
                "tool_name": "nonexistent_tool",
                "tool_arguments": {},
            },
        )

        assert result["exit_code"] == 1
        assert "not available" in result["output"].lower()
        assert "error" in result


class TestMCPToolSchemaTranslation:
    """Test schema translation for MCP tool parameters."""

    @pytest.mark.asyncio
    async def test_schema_translation_file_path_to_path(self, tool_executor):
        """Test that file_path is translated to path."""
        # This tests the _translate_mcp_tool_schema method indirectly
        translated = tool_executor._translate_mcp_tool_schema(
            "custom_tool", {"file_path": "/test/file.txt", "other": "value"}
        )

        assert "path" in translated
        assert translated["path"] == "/test/file.txt"
        assert translated["other"] == "value"

    @pytest.mark.asyncio
    async def test_schema_translation_search_pattern_to_pattern(self, tool_executor):
        """Test that search_pattern is translated to pattern."""
        translated = tool_executor._translate_mcp_tool_schema(
            "search_tool", {"search_pattern": "*.py"}
        )

        assert "pattern" in translated
        assert translated["pattern"] == "*.py"

    @pytest.mark.asyncio
    async def test_schema_translation_preserves_unmapped_params(self, tool_executor):
        """Test that unmapped parameters are preserved."""
        translated = tool_executor._translate_mcp_tool_schema(
            "custom_tool", {"custom_param": "value", "another": 123}
        )

        assert translated["custom_param"] == "value"
        assert translated["another"] == 123


class TestPatchFileToolTranslation:
    """Test patch_file tool translation and execution."""

    @pytest.mark.asyncio
    async def test_translate_patch_file_with_diff(self, translator):
        """Test translating patch_file tool with diff."""
        xml = """<use_mcp_tool name="patch_file">
            <arguments>
                <diff>--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
+    print("world")
     pass
</diff>
            </arguments>
        </use_mcp_tool>"""

        result = await translator.translate_tool_invocation(xml)

        assert result is not None
        tool_name, arguments = result
        assert tool_name == "__proxy_use_mcp_tool"
        assert arguments["tool_name"] == "patch_file"
        assert "diff" in arguments["tool_arguments"]
        assert "--- a/file.py" in arguments["tool_arguments"]["diff"]

    @pytest.mark.asyncio
    async def test_execute_patch_file_tool(self, tool_executor, mock_mcp_server):
        """Test executing patch_file tool."""
        diff_content = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
+    print("world")
     pass
"""

        result = await tool_executor.execute_tool(
            "__proxy_use_mcp_tool",
            {
                "tool_name": "patch_file",
                "tool_arguments": {"diff": diff_content, "path": "file.py"},
            },
        )

        assert result["exit_code"] == 0
        assert "applied patch" in result["output"].lower()

        # Verify the tool was called
        assert len(mock_mcp_server.call_history) == 1
        call = mock_mcp_server.call_history[0]
        assert call["tool"] == "patch_file"
        assert "diff" in call["arguments"]


class TestMCPBridgeErrorHandling:
    """Test error handling in MCP bridge."""

    @pytest.mark.asyncio
    async def test_missing_tool_name_in_use_mcp_tool(self, translator):
        """Test that missing tool_name raises error."""
        xml = """<use_mcp_tool>
            <arguments>
                <param>value</param>
            </arguments>
        </use_mcp_tool>"""

        with pytest.raises(TranslationError) as exc_info:
            await translator.translate_tool_invocation(xml)

        # XML parsing error is caught first, so we get COMPAT_E002
        assert exc_info.value.error_code == "COMPAT_E002"
        assert "name" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_missing_tool_name(self, tool_executor):
        """Test executing use_mcp_tool without tool_name."""
        result = await tool_executor.execute_tool(
            "__proxy_use_mcp_tool", {"tool_arguments": {}}
        )

        assert result["exit_code"] == 1
        assert "tool_name is required" in result["output"].lower()

    @pytest.mark.asyncio
    async def test_execute_access_mcp_resource_missing_uri(self, tool_executor):
        """Test executing access_mcp_resource without URI."""
        result = await tool_executor.execute_tool("__proxy_access_mcp_resource", {})

        assert result["exit_code"] == 1
        assert "uri is required" in result["output"].lower()


class TestMCPBridgeResultFormatting:
    """Test result formatting for MCP tools in KiloCode format."""

    @pytest.mark.asyncio
    async def test_mcp_tool_result_formatted_with_tool_name(self, tool_executor):
        """Test that MCP tool results are formatted with tool name prefix."""
        result = await tool_executor.execute_tool(
            "__proxy_use_mcp_tool",
            {
                "tool_name": "custom_tool",
                "tool_arguments": {"param1": "test"},
            },
        )

        assert result["exit_code"] == 0
        assert result["output"].startswith("[custom_tool] Result:")

    @pytest.mark.asyncio
    async def test_access_mcp_resource_result_formatted(self, tool_executor):
        """Test that access_mcp_resource results are formatted correctly."""
        result = await tool_executor.execute_tool(
            "__proxy_access_mcp_resource", {"uri": "file://test/resource.txt"}
        )

        assert result["exit_code"] == 0
        assert result["output"].startswith("[access_mcp_resource] Result:")
        assert "test resource content" in result["output"].lower()
