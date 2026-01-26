
"""Tests for Gemini translation of reasoning content."""

from src.core.domain.translators.gemini.response import gemini_to_domain_response
from src.core.domain.translators.gemini.streaming import gemini_to_domain_stream_chunk


class TestGeminiTranslationReasoning:
    """Tests for converting Gemini responses with reasoning to domain format."""

    def test_response_with_reasoning_content(self) -> None:
        """Test non-streaming translation handles reasoning type parts."""
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "I am thinking about the answer.", "type": "reasoning"},
                            {"text": "Here is the final answer."}
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ]
        }
        
        canonical = gemini_to_domain_response(response)
        
        assert len(canonical.choices) == 1
        assert canonical.choices[0].message.content == "Here is the final answer."
        assert canonical.choices[0].message.reasoning_content == "I am thinking about the answer."

    def test_response_with_thinking_metadata(self) -> None:
        """Test non-streaming translation handles text parts with thinking metadata."""
        response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "Thought process...",
                                "metadata": {"type": "thinking"}
                            },
                            {"text": "Final answer."}
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ]
        }
        
        canonical = gemini_to_domain_response(response)
        
        assert len(canonical.choices) == 1
        assert canonical.choices[0].message.content == "Final answer."
        # Metadata thinking should be extracted to reasoning_content
        assert canonical.choices[0].message.reasoning_content == "Thought process..."

    def test_streaming_reasoning_content(self) -> None:
        """Test streaming translation handles reasoning type parts."""
        chunk = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "I am thinking...", "type": "reasoning"}
                        ]
                    }
                }
            ]
        }
        
        canonical_chunk = gemini_to_domain_stream_chunk(chunk)
        if isinstance(canonical_chunk, dict):
             choices = canonical_chunk["choices"]
             delta = choices[0]["delta"]
             reasoning = delta["reasoning_content"]
             content = delta.get("content")
        else:
             delta = canonical_chunk.choices[0].delta
             reasoning = delta.reasoning_content
             content = delta.content
        
        assert reasoning == "I am thinking..."
        assert content is None
