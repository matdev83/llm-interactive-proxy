
"""Regression tests for Gemini request translation bugs."""

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    ToolCall,
)
from src.core.domain.translators.gemini.request import from_domain_to_gemini_request


class TestGeminiRequestRegression:
    """Regression tests for Gemini request translation."""

    def test_regression_tool_calls_with_reasoning_content(self) -> None:
        """
        Regression test: Ensure that when an assistant message has both `tool_calls`
        and `reasoning_content`, the reasoning content is NOT dropped.
        
        Previous behavior: If `tool_calls` were present, other content parts were skipped.
        Fixed behavior: Both tool calls and text content (including reasoning) are included.
        """
        messages = [
            ChatMessage(role="user", content="Do something"),
            ChatMessage(
                role="assistant",
                # This is the "thought" or reasoning content
                reasoning_content="I should call the tool now.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="my_tool", arguments="{}")
                    )
                ]
            )
        ]
        
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=messages
        )

        gemini_request = from_domain_to_gemini_request(request)
        
        assert len(gemini_request["contents"]) == 2
        assistant_msg = gemini_request["contents"][1]
        assert assistant_msg["role"] == "model"
        
        parts = assistant_msg["parts"]
        
        # Verify tool call is present
        tool_call_parts = [p for p in parts if "functionCall" in p]
        assert len(tool_call_parts) == 1
        assert tool_call_parts[0]["functionCall"]["name"] == "my_tool"
        
        # Verify reasoning/text content is present
        # The translator converts reasoning_content to a text part
        text_parts = [p for p in parts if "text" in p]
        assert len(text_parts) >= 1
        assert any("I should call the tool now" in p["text"] for p in text_parts)

    def test_regression_tool_calls_with_regular_content(self) -> None:
        """
        Regression test: Ensure that when an assistant message has both `tool_calls`
        and regular `content`, the content is NOT dropped.
        """
        messages = [
            ChatMessage(role="user", content="Do something"),
            ChatMessage(
                role="assistant",
                content="Here is some text before the tool call.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="my_tool", arguments="{}")
                    )
                ]
            )
        ]
        
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=messages
        )

        gemini_request = from_domain_to_gemini_request(request)
        
        assistant_msg = gemini_request["contents"][1]
        parts = assistant_msg["parts"]
        
        # Verify tool call is present
        tool_call_parts = [p for p in parts if "functionCall" in p]
        assert len(tool_call_parts) == 1
        
        # Verify content is present
        text_parts = [p for p in parts if "text" in p]
        assert len(text_parts) >= 1
        assert any("Here is some text" in p["text"] for p in text_parts)
