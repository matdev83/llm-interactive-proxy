from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx
from fastapi import HTTPException
from starlette.responses import StreamingResponse

from src.connectors.base import LLMBackend
from src.models import (
    ChatCompletionRequest,
    MessageContentPartText,
    # Potentially others if we handle complex content for the prompt
)
from src.security import APIKeyRedactor

# Import MCP client parts if they are directly used and typed
# from mcp.client.session import ClientSession
# from mcp.client.streamable_http import streamablehttp_client
# from mcp.exceptions import MCPError

# For now, assume we might need to manually construct/parse JSON-RPC if SDK use is tricky with httpx client from main.py
# Or, we might instantiate a new httpx.AsyncClient for the MCP SDK if that's cleaner.

logger = logging.getLogger(__name__)


class GeminiCliBackend(LLMBackend):
    """LLMBackend implementation for the Gemini CLI MCP Tool."""

    def __init__(self, client: httpx.AsyncClient, mcp_server_url: str | None):
        self.client = client # This is the shared httpx client from main.py
        self.mcp_server_url = mcp_server_url
        self.available_models: list[str] = [] # Placeholder for now

    async def initialize(self) -> None:
        """
        Initializes the backend. For GeminiCliBackend, this could involve
        a health check to the MCP server or pre-fetching capabilities.
        For now, it's a no-op if no immediate initialization is needed
        beyond having the URL.
        """
        if not self.mcp_server_url:
            logger.warning("Gemini CLI MCP server URL not configured. Backend will not be functional.")
            return

        # Simple check: try to list tools as a basic health check.
        # This requires knowing the exact JSON-RPC method and structure.
        # For now, we'll assume the URL being present is enough, and actual calls will reveal issues.
        # A more robust initialize would make a test call (e.g., list_tools)
        # using the MCP Python SDK if it's to be used.

        # For now, let's assume a default model if model listing isn't straightforward.
        self.available_models = ["gemini-pro"] # Default model via CLI, can be overridden by user
        logger.info(f"Gemini CLI backend initialized with MCP server URL: {self.mcp_server_url}")
        # Actual test connection might be better here.

    def get_available_models(self) -> list[str]:
        """Return available models for Gemini CLI. This might be a fixed list
        or determined by querying the MCP tool if it supports model listing."""
        # If the MCP tool itself manages model selection via Gemini CLI,
        # this list might just indicate that the backend is available.
        # The `ask-gemini` tool in gemini-mcp-tool takes a `model` param.
        return self.available_models or ["gemini-mcp-default"]


    async def chat_completions(
        self,
        request_data: ChatCompletionRequest,
        processed_messages: list,
        effective_model: str, # This is the model name to be passed to ask-gemini
        project: str | None = None, # MCP tool might not use this
        prompt_redactor: APIKeyRedactor | None = None,
        # These are from LLMBackend but might not be used by this specific backend
        openrouter_api_base_url: Optional[str] = None,
        openrouter_headers_provider: object = None,
        key_name: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs, # For any other specific params this backend might need from config
    ) -> Union[StreamingResponse, Dict[str, Any]]:

        if not self.mcp_server_url:
            raise HTTPException(status_code=500, detail="Gemini CLI MCP server URL is not configured.")

        # 1. Construct the prompt for 'ask-gemini'
        user_prompt_parts = []
        for msg in processed_messages:
            if msg.role == "user": # Or based on what gemini-mcp-tool expects
                if isinstance(msg.content, str):
                    user_prompt_parts.append(msg.content)
                elif isinstance(msg.content, list):
                    for part in msg.content:
                        if isinstance(part, MessageContentPartText):
                            user_prompt_parts.append(part.text)
                        # Handle other part types if gemini-mcp-tool's ask-gemini supports them (e.g., @file syntax)

        user_prompt_text = "\n".join(user_prompt_parts)
        if prompt_redactor:
            user_prompt_text = prompt_redactor.redact(user_prompt_text)

        if not user_prompt_text:
            raise HTTPException(status_code=400, detail="No prompt content found for Gemini CLI tool.")

        # 2. Prepare JSON-RPC request for MCP `callTool`
        # The exact method name ('tool/call' or similar) and params structure
        # should align with the MCP specification and Python SDK usage.
        # Let's assume ClientSession().call_tool("ask-gemini", args) translates to:
        # Method: "tool/call" (standard MCP method)
        # Params: {"name": "ask-gemini", "arguments": {"prompt": user_prompt_text, "model": effective_model}}
        # (The `model` param for `ask-gemini` is based on gemini-mcp-tool's README)

        mcp_request_payload = {
            "jsonrpc": "2.0",
            "method": "tool/call", # This is a guess, need to confirm from MCP spec or Python SDK source
            "params": {
                "name": "ask-gemini",
                "arguments": {
                    "prompt": user_prompt_text,
                }
            },
            "id": secrets.token_hex(8) # Unique request ID
        }
        if effective_model: # Pass model if specified
             mcp_request_payload["params"]["arguments"]["model"] = effective_model


        # 3. Send request to MCP server
        try:
            # Using the shared httpx client instance from main.py
            response = await self.client.post(
                self.mcp_server_url,
                json=mcp_request_payload,
                # Headers might be needed, e.g., Content-Type: application/json
                # The MCP Python SDK's streamablehttp_client would handle these.
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            mcp_response_data = response.json()

        except httpx.RequestError as e:
            logger.error(f"Request error connecting to Gemini CLI MCP server: {e}", exc_info=True)
            raise HTTPException(status_code=503, detail=f"Service unavailable: Could not connect to Gemini CLI MCP server ({e})")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Gemini CLI MCP server: {e.response.status_code} - {e.response.text}", exc_info=True)
            try:
                error_detail = e.response.json()
            except json.JSONDecodeError:
                error_detail = e.response.text
            raise HTTPException(status_code=e.response.status_code, detail=error_detail)

        # 4. Parse MCP JSON-RPC response
        if "error" in mcp_response_data:
            error_obj = mcp_response_data["error"]
            logger.error(f"Error from Gemini CLI MCP tool: {error_obj}")
            raise HTTPException(status_code=500, detail=f"Gemini CLI tool error: {error_obj.get('message', 'Unknown error')}")

        mcp_result = mcp_response_data.get("result", {})

        # The structure of mcp_result.content is based on MCP SDK examples:
        # e.g., { "content": [{ "type": "text", "text": "response..." }] }
        tool_content_parts = mcp_result.get("content", [])
        llm_response_text = ""
        for part in tool_content_parts:
            if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                llm_response_text += part["text"]

        if not llm_response_text and not tool_content_parts: # If content was empty or not in expected format
             logger.warning(f"Gemini CLI MCP tool returned no parsable text content. Full result: {mcp_result}")
             # llm_response_text will remain empty, leading to an empty response or handled by OpenAI formatting.


        # 5. Convert to OpenAI ChatCompletion format
        # For now, non-streaming. Streaming would require the MCP tool to support it
        # and for us to handle the MCP streaming mechanism.

        # TODO: Determine how to get token counts if MCP tool provides them.
        # For now, using 0.
        final_response = {
            "id": f"chatcmpl-geminicli-{secrets.token_hex(8)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": effective_model, # Or the model reported by MCP tool if available
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": llm_response_text,
                    },
                    "finish_reason": "stop", # Assuming 'stop' if successful
                }
            ],
            "usage": {
                "prompt_tokens": 0, # Placeholder
                "completion_tokens": 0, # Placeholder
                "total_tokens": 0, # Placeholder
            },
        }

        if request_data.stream:
            # If streaming is requested, but we don't support it yet for this backend,
            # we could either raise an error or return a single chunk followed by [DONE].
            # For now, let's return a single chunk for simplicity if stream=True.
            # This isn't true SSE streaming but fulfills the immediate contract.
            async def stream_generator() -> AsyncGenerator[bytes, None]:
                chunk_response = {
                    "id": final_response["id"],
                    "object": "chat.completion.chunk",
                    "created": final_response["created"],
                    "model": final_response["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": llm_response_text},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk_response)}\n\n".encode()
                yield b"data: [DONE]\n\n"

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        return final_response

    # TODO: Implement actual usage of MCP Python SDK's ClientSession and streamablehttp_client
    # This would replace the manual JSON-RPC construction and httpx.post call.
    # Using the SDK would be more robust for handling MCP specifics.
    # Example using SDK (conceptual, needs adaptation):
    #
    # from mcp import ClientSession, types
    # from mcp.client.streamable_http import streamablehttp_client
    # from urllib.parse import urlparse
    #
    # async def call_mcp_tool_with_sdk(self, mcp_url: str, tool_name: str, args: dict, model_name: str | None) -> Any:
    #     parsed_url = urlparse(mcp_url)
    #     base_url_for_sdk = f"{parsed_url.scheme}://{parsed_url.netloc}"
    #     path_for_sdk = parsed_url.path.lstrip('/')
    #
    #     tool_args = args.copy()
    #     if model_name:
    #         tool_args["model"] = model_name
    #
    #     async with streamablehttp_client(base_url_for_sdk, path_prefix=path_for_sdk) as (read, write, _):
    #         async with ClientSession(read, write) as session:
    #             await session.initialize() # Add client capabilities if needed
    #             # Example capabilities:
    #             # capabilities = types.ClientCapabilities(tools=types.ToolClientCapabilities())
    #             # await session.initialize(client_name="llm-interactive-proxy", client_version="0.1.0", capabilities=capabilities)
    #
    #             logger.debug(f"Calling MCP tool '{tool_name}' with args: {tool_args} via SDK")
    #             result = await session.call_tool(tool_name, arguments=tool_args)
    #             # result is likely a Pydantic model from the SDK, e.g., CallToolResult
    #             # Access result.content, result.isError etc.
    #             if result.isError:
    #                 # Handle error content
    #                 error_content_text = ""
    #                 if result.content:
    #                     for part in result.content:
    #                         if part.type == "text":
    #                             error_content_text += part.text
    #                 raise HTTPException(status_code=500, detail=f"MCP Tool Error: {error_content_text or 'Unknown error'}")
    #             return result # This would be CallToolResult object
    #
    # Then, in chat_completions, replace the httpx.post block with:
    # try:
    #   mcp_sdk_result = await self.call_mcp_tool_with_sdk(
    #       self.mcp_server_url,
    #       "ask-gemini",
    #       {"prompt": user_prompt_text},
    #       effective_model
    #   )
    #   # Process mcp_sdk_result.content to extract llm_response_text
    #   llm_response_text = ""
    #   if mcp_sdk_result.content:
    #       for part in mcp_sdk_result.content:
    #           if part.type == "text": # Assuming TextPart from mcp.types
    #               llm_response_text += part.text
    #
    # except MCPError as e: # Catch specific MCP SDK errors
    #   logger.error(f"MCP SDK error: {e}", exc_info=True)
    #   raise HTTPException(status_code=500, detail=f"MCP communication error: {e}")
    # except Exception as e: # Catch other errors like connection issues if not caught by SDK
    #   logger.error(f"Error calling MCP tool via SDK: {e}", exc_info=True)
    #   raise HTTPException(status_code=503, detail=f"Failed to call Gemini CLI MCP tool: {e}")
    #
    # The rest of the OpenAI response formatting would remain similar.
    # Streaming with the SDK would need investigation into how call_tool handles streaming results.
    # The MCP SDK's streamablehttp_client and ClientSession are async context managers,
    # so they should be used with `async with`. The shared self.client from FastAPI might not be
    # directly usable or ideal for the MCP SDK's transport which expects to manage the connection.
    # A new httpx.AsyncClient could be instantiated per call for the SDK, or managed by the SDK's transport.
    # The streamablehttp_client itself likely creates its own httpx client or takes one.
    # For simplicity, the current manual httpx call is a starting point.
    # Refactoring to use the MCP Python SDK is a strong recommendation for robustness.

```
