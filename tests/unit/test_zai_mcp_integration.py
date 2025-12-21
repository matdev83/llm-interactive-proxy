"""Integration test demonstrating MCP tool call extraction in ZAI backend."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.services import register_core_services
from src.core.domain.chat import ChatRequest


class TestZaiMCPIntegration:
    """Test MCP tool call extraction in realistic scenarios."""

    @pytest.fixture
    async def backend(self):
        """Create a ZAI backend instance for testing."""
        # Set up DI container with ToolCallRepairService
        # register_core_services should register ToolCallRepairService via register_application_state_services
        from src.core.di.services import set_service_provider

        collection = ServiceCollection()
        register_core_services(collection, None)
        provider = collection.build_service_provider()
        set_service_provider(provider)

        mock_client = AsyncMock()
        mock_config = MagicMock(spec=AppConfig)
        mock_config.backends = MagicMock()
        mock_config.backends.zai_coding_plan = None

        backend = ZaiCodingPlanBackend(
            client=mock_client,
            config=mock_config,
        )

        # Initialize with test API key
        await backend.initialize(api_key="test_key_12345678")

        return backend

    @pytest.mark.asyncio
    async def test_prepare_payload_extracts_mcp_tools(self, backend):
        """Test that _prepare_payload extracts MCP tool calls from messages."""
        # Create a request with MCP tool invocation in message content
        request = ChatRequest(
            model="glm-4.6",
            messages=[
                {
                    "role": "user",
                    "content": "Please patch the file",
                },
                {
                    "role": "assistant",
                    "content": 'I will patch the file now.\n\n<use_mcp_tool tool_name="patch_file"><path>src/main.py</path><diff>--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,3 @@\n-old code\n+new code</diff></use_mcp_tool>',
                },
            ],
        )

        # Prepare payload
        payload = await backend._prepare_payload(request, request.messages, "glm-4.6")

        # Verify the payload has proper structure
        assert "messages" in payload
        assert len(payload["messages"]) == 2

        # Check the assistant message
        assistant_msg = payload["messages"][1]
        assert assistant_msg["role"] == "assistant"

        # Verify tool_calls were extracted
        assert "tool_calls" in assistant_msg
        assert len(assistant_msg["tool_calls"]) == 1

        tool_call = assistant_msg["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "patch_file"

        # Verify arguments were parsed correctly
        args = json.loads(tool_call["function"]["arguments"])
        assert args["path"] == "src/main.py"
        assert "diff" in args
        assert "old code" in args["diff"]
        assert "new code" in args["diff"]

        # Verify XML was removed from content
        assert "<use_mcp_tool" not in assistant_msg["content"]
        assert "I will patch the file now." in assistant_msg["content"]

    @pytest.mark.asyncio
    async def test_multiple_mcp_tools_in_conversation(self, backend):
        """Test extraction of multiple MCP tools across conversation."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[
                {"role": "user", "content": "Read two files"},
                {
                    "role": "assistant",
                    "content": '<use_mcp_tool tool_name="read_file"><path>file1.py</path></use_mcp_tool>\n\n<use_mcp_tool tool_name="read_file"><path>file2.py</path></use_mcp_tool>',
                },
            ],
        )

        payload = await backend._prepare_payload(request, request.messages, "glm-4.6")

        assistant_msg = payload["messages"][1]
        assert "tool_calls" in assistant_msg
        assert len(assistant_msg["tool_calls"]) == 2

        # Verify both tool calls
        assert assistant_msg["tool_calls"][0]["function"]["name"] == "read_file"
        assert assistant_msg["tool_calls"][1]["function"]["name"] == "read_file"

        args1 = json.loads(assistant_msg["tool_calls"][0]["function"]["arguments"])
        args2 = json.loads(assistant_msg["tool_calls"][1]["function"]["arguments"])

        assert args1["path"] == "file1.py"
        assert args2["path"] == "file2.py"

    @pytest.mark.asyncio
    async def test_mixed_content_and_tools(self, backend):
        """Test that text content is preserved alongside tool calls."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[
                {"role": "user", "content": "Fix the bug"},
                {
                    "role": "assistant",
                    "content": 'I found the issue. Let me fix it.\n\n<use_mcp_tool tool_name="patch_file"><path>bug.py</path><content>fixed</content></use_mcp_tool>\n\nThis should resolve the problem.',
                },
            ],
        )

        payload = await backend._prepare_payload(request, request.messages, "glm-4.6")

        assistant_msg = payload["messages"][1]

        # Verify tool call was extracted
        assert "tool_calls" in assistant_msg
        assert len(assistant_msg["tool_calls"]) == 1

        # Verify surrounding text was preserved
        content = assistant_msg["content"]
        assert "I found the issue" in content
        assert "This should resolve the problem" in content
        assert "<use_mcp_tool" not in content

    @pytest.mark.asyncio
    async def test_no_extraction_for_non_mcp_content(self, backend):
        """Test that regular messages are not modified."""
        request = ChatRequest(
            model="glm-4.6",
            messages=[
                {"role": "user", "content": "Hello"},
                {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
            ],
        )

        payload = await backend._prepare_payload(request, request.messages, "glm-4.6")

        assistant_msg = payload["messages"][1]

        # Verify no tool_calls were added
        assert "tool_calls" not in assistant_msg or not assistant_msg.get("tool_calls")

        # Verify content is unchanged
        assert assistant_msg["content"] == "Hello! How can I help you today?"
