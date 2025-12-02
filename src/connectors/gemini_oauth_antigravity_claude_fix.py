"""
Patch for gemini_oauth_antigravity.py to add Claude support.

Add these methods to GeminiOAuthAntigravityConnector class.
"""

import json
from typing import Any

def _is_claude_model(self, model_name: str) -> bool:
    """Check if the model is a Claude model."""
    return "claude" in model_name.lower()

def _convert_to_anthropic_messages(self, request: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Convert domain request messages to Anthropic format.
    
    Returns:
        Tuple of (messages_list, system_message)
    """
    from src.core.domain.chat import CanonicalChatRequest
    
    # Ensure we have CanonicalChatRequest
    if not isinstance(request, CanonicalChatRequest):
        if isinstance(request, dict):
            request = CanonicalChatRequest.model_validate(request)
        else:
            request = CanonicalChatRequest.model_validate(request.model_dump())
    
    anthropic_messages = []
    system_message = None
    
    for msg in request.messages:
        if msg.role == "system":
            # Extract system message (Anthropic uses separate 'system' parameter)
            system_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            continue
        
        role = msg.role
        content: list[dict[str, Any]] = []
        
        # Handle text content
        if msg.content:
            if isinstance(msg.content, str):
                content.append({"type": "text", "text": msg.content})
            elif isinstance(msg.content, list):
                # Handle multimodal content
                for part in msg.content:
                    if hasattr(part, "text"):
                        content.append({"type": "text", "text": part.text})
                    elif hasattr(part, "type") and part.type == "text":
                        text = getattr(part, "text", "")
                        content.append({"type": "text", "text": text})
        
        # Handle tool calls in assistant messages
        if role == "assistant" and msg.tool_calls:
            for tc in msg.tool_calls:
                tc_dict = tc if isinstance(tc, dict) else tc.model_dump()
                fn = tc_dict.get("function", {})
                args_str = fn.get("arguments", "{}")
                
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception:
                    args = {}
                
                content.append({
                    "type": "tool_use",
                    "id": tc_dict.get("id", f"toolu_{id(tc)}"),
                    "name": fn.get("name", ""),
                    "input": args
                })
        
        # Handle tool results (map 'tool' role to 'user' with tool_result)
        if role == "tool":
            role = "user"
            tool_use_id = msg.tool_call_id or f"toolu_unknown_{id(msg)}"
            tool_content = msg.content or ""
            
            content = [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": tool_content
            }]
        
        if content:
            anthropic_messages.append({"role": role, "content": content})
    
    return anthropic_messages, system_message

def _convert_tools_to_anthropic(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert tools definition to Anthropic format."""
    if not tools:
        return []
    
    anthropic_tools = []
    for tool in tools:
        if "function" in tool:
            fn = tool["function"]
            anthropic_tools.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {})
            })
    return anthropic_tools
