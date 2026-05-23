"""Tests for think tags fix middleware reasoning preservation functionality."""

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.think_tags_fix_middleware import ThinkTagsFixMiddleware


class TestThinkTagsReasoningPreservation:
    """Test cases for reasoning preservation in ThinkTagsFixMiddleware."""

    @pytest.mark.asyncio
    async def test_openai_style_response_formatting(self):
        """Test that OpenAI-style responses get reasoning field added."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        openai_response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "<think>Let me analyze this step by step</think>The answer is 42.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

        result = await middleware.process(openai_response, "session1", {})

        # Check that response structure is preserved
        assert result["id"] == "chatcmpl-123"
        assert result["object"] == "chat.completion"
        assert result["usage"]["total_tokens"] == 30

        # Check that content is fixed and reasoning is preserved
        message = result["choices"][0]["message"]
        assert message["content"] == "The answer is 42."
        assert message["reasoning"] == "Let me analyze this step by step"
        assert message["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_dict_response_formatting(self):
        """Test that dict responses get reasoning in metadata."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        dict_response = {
            "content": "<think>My reasoning process</think>Final answer",
            "usage": {"tokens": 50},
            "model": "test-model",
        }

        result = await middleware.process(dict_response, "session1", {})

        # Check that response structure is preserved
        assert result["usage"]["tokens"] == 50
        assert result["model"] == "test-model"

        # Check that content is fixed and reasoning is in metadata
        assert result["content"] == "Final answer"
        assert result["metadata"]["reasoning"] == "My reasoning process"
        assert result["metadata"]["reasoning_format"] == "extracted_from_think_tags"

    @pytest.mark.asyncio
    async def test_processed_response_formatting(self):
        """Test that ProcessedResponse gets reasoning in metadata."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        response = ProcessedResponse(
            content="<think>Complex reasoning here</think>Simple answer",
            usage={"tokens": 100},
            metadata={"original": "data"},
        )

        result = await middleware.process(response, "session1", {})

        # Check that response structure is preserved
        assert result.usage["tokens"] == 100
        assert result.metadata["original"] == "data"

        # Check that content is fixed and reasoning is preserved
        assert result.content == "Simple answer"
        assert result.metadata["reasoning"] == "Complex reasoning here"
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_multiline_reasoning_preservation(self):
        """Test that multiline reasoning is properly preserved."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = """<think>
First, I need to understand the problem.
Then, I'll analyze the requirements.
Finally, I'll provide a solution.
</think>Here's my recommendation: use approach A."""

        response = ProcessedResponse(content=content)
        result = await middleware.process(response, "session1", {})

        expected_reasoning = """First, I need to understand the problem.
Then, I'll analyze the requirements.
Finally, I'll provide a solution."""

        assert result.content == "Here's my recommendation: use approach A."
        assert result.metadata["reasoning"] == expected_reasoning
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"

    @pytest.mark.asyncio
    async def test_pure_reasoning_content(self):
        """Test handling of content that is pure reasoning."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "<think>This is just reasoning without any actual response"
        response = ProcessedResponse(content=content)
        result = await middleware.process(response, "session1", {})

        # Should return empty content with reasoning preserved
        assert result.content == ""
        assert (
            result.metadata["reasoning"]
            == "This is just reasoning without any actual response"
        )
        assert result.metadata["reasoning_format"] == "extracted_from_think_tags"
        assert result.metadata["think_tags_fixed"] is True

    @pytest.mark.asyncio
    async def test_reasoning_length_tracking(self):
        """Test that reasoning and content lengths are tracked."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        reasoning = "This is detailed reasoning"
        content_text = "Short answer"
        full_content = f"<think>{reasoning}</think>{content_text}"

        response = ProcessedResponse(content=full_content)
        result = await middleware.process(response, "session1", {})

        assert result.content == content_text
        assert result.metadata["reasoning"] == reasoning
        assert result.metadata["reasoning_length"] == len(reasoning)
        assert result.metadata["fixed_content_length"] == len(content_text)
        # Note: original_content_length tracks the string representation of the original response
        assert result.metadata["original_content_length"] > 0

    @pytest.mark.asyncio
    async def test_no_reasoning_content_unchanged(self):
        """Test that content without reasoning is unchanged."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        content = "Normal response without any reasoning tags"
        response = ProcessedResponse(content=content)
        result = await middleware.process(response, "session1", {})

        # Should return original response unchanged
        assert result.content == content
        # No reasoning metadata should be added
        assert result.metadata is None or "reasoning" not in result.metadata

    @pytest.mark.asyncio
    async def test_client_reasoning_handling_example(self):
        """Test example of how clients can handle the preserved reasoning."""
        middleware = ThinkTagsFixMiddleware(enabled=True)

        # Simulate a problematic model response
        problematic_content = """<think>
The user is asking about Python functions. I should:
1. Explain the basic syntax
2. Provide a clear example
3. Mention parameters and return values
</think>Here's how to define a function in Python:

```python
def greet(name):
    return f"Hello, {name}!"
```

This function takes a name parameter and returns a greeting."""

        response = ProcessedResponse(content=problematic_content)
        result = await middleware.process(response, "session1", {})

        # Verify the response is properly formatted
        expected_content = """Here's how to define a function in Python:

```python
def greet(name):
    return f"Hello, {name}!"
```

This function takes a name parameter and returns a greeting."""

        expected_reasoning = """The user is asking about Python functions. I should:
1. Explain the basic syntax
2. Provide a clear example
3. Mention parameters and return values"""

        assert result.content == expected_content
        assert result.metadata["reasoning"] == expected_reasoning

        # Demonstrate how a client could handle this
        def simulate_client_handling(response_obj):
            """Simulate how a client would handle the response."""
            main_content = response_obj.content
            reasoning = response_obj.metadata.get("reasoning")

            # Client can now choose how to display reasoning
            if reasoning:
                return {
                    "main_response": main_content,
                    "thinking_process": reasoning,
                    "show_reasoning": True,
                }
            else:
                return {"main_response": main_content, "show_reasoning": False}

        client_result = simulate_client_handling(result)
        assert client_result["main_response"] == expected_content
        assert client_result["thinking_process"] == expected_reasoning
        assert client_result["show_reasoning"] is True
