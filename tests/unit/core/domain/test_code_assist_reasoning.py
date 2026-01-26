
"""Tests for Code Assist translation of reasoning content."""

import json
from src.core.domain.translators.code_assist.streaming import code_assist_to_domain_stream_chunk
from src.core.domain.translators.code_assist.response import code_assist_to_domain_response

class TestCodeAssistTranslationReasoning:
    """Tests for converting Code Assist responses with reasoning to domain format."""

    def test_streaming_reasoning_content(self) -> None:
        """Test streaming translation handles reasoning type parts."""
        chunk = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"type": "reasoning", "text": "I am thinking about code."},
                                {"text": "Here is the code."}
                            ]
                        }
                    }
                ]
            }
        }
        
        domain_chunk = code_assist_to_domain_stream_chunk(chunk)
        choices = domain_chunk["choices"]
        assert len(choices) == 1
        delta = choices[0]["delta"]
        
        # Should have content AND reasoning_content
        assert delta.get("content") == "Here is the code."
        assert delta.get("reasoning_content") == "I am thinking about code."

    def test_streaming_thinking_metadata(self) -> None:
        """Test streaming translation handles text parts with thinking metadata."""
        chunk = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "Thought process...",
                                    "metadata": {"type": "thinking"}
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
        domain_chunk = code_assist_to_domain_stream_chunk(chunk)
        choices = domain_chunk["choices"]
        assert len(choices) == 1
        delta = choices[0]["delta"]
        
        # Should be in BOTH content (because it's text) and reasoning_content (because of metadata)
        # This matches Gemini translator behavior
        assert delta.get("content") == "Thought process..."
        assert delta.get("reasoning_content") == "Thought process..."

    def test_response_reasoning_content(self) -> None:
        """Test non-streaming translation handles reasoning type parts."""
        response = {
            "response": {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"type": "reasoning", "text": "I am thinking."},
                                {"text": "Final answer."}
                            ]
                        },
                        "finishReason": "STOP"
                    }
                ]
            }
        }
        
        domain_response = code_assist_to_domain_response(response)
        choice = domain_response.choices[0]
        
        assert choice.message.content == "Final answer."
        assert choice.message.reasoning_content == "I am thinking."
