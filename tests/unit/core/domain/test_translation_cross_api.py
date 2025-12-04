"""
Tests for cross-API translation functionality.

This module tests the translation between different API formats:
- OpenAI frontend to Gemini backend
- OpenAI frontend to Gemini OAuth backend
- OpenAI frontend to Gemini Cloud Project backend
- OpenAI frontend to Anthropic backend
"""

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionDefinition,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
    ToolDefinition,
)
from src.core.domain.translation import Translation


class TestOpenAIToGeminiTranslation:
    """Tests for OpenAI to Gemini translation."""

    def test_simple_text_message(self) -> None:
        """Test translation of simple text messages."""
        # Create a canonical chat request with simple text messages
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello, how are you?"),
            ChatMessage(
                role="assistant", content="I'm doing well, how can I help you today?"
            ),
            ChatMessage(role="user", content="Tell me about Python."),
        ]
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1000,
            stop=["END"],
        )

        # Translate to Gemini format
        gemini_request = Translation.from_domain_to_gemini_request(request)

        # Verify the translation
        assert "contents" in gemini_request
        assert "generationConfig" in gemini_request

        # Check contents
        contents = gemini_request["contents"]
        assert len(contents) == 4  # All messages including system

        # Check user message
        user_messages = [m for m in contents if m["role"] == "user"]
        assert len(user_messages) == 2
        assert user_messages[0]["parts"][0]["text"] == "Hello, how are you?"

        # Gemini API does not accept the assistant role label
        assert all(m["role"] != "assistant" for m in contents)

        # Check model-side message (assistant in canonical form)
        model_messages = [m for m in contents if m["role"] == "model"]
        assert len(model_messages) == 1
        assert (
            model_messages[0]["parts"][0]["text"]
            == "I'm doing well, how can I help you today?"
        )

        # Check generation config
        gen_config = gemini_request["generationConfig"]
        assert gen_config["temperature"] == 0.7
        assert gen_config["topP"] == 0.9
        assert gen_config["maxOutputTokens"] == 1000
        assert gen_config["stopSequences"] == ["END"]

    def test_multimodal_content(self) -> None:
        """Test translation of multimodal content."""
        # Create a canonical chat request with multimodal content
        text_part = MessageContentPartText(text="Describe this image:")
        image_part = MessageContentPartImage(
            image_url=ImageURL(url="https://example.com/image.jpg", detail=None)
        )

        messages = [
            ChatMessage(role="user", content=[text_part, image_part]),
        ]
        request = CanonicalChatRequest(
            model="gemini-1.5-pro-vision",
            messages=messages,
        )

        # Translate to Gemini format
        gemini_request = Translation.from_domain_to_gemini_request(request)

        # Verify the translation
        assert "contents" in gemini_request
        contents = gemini_request["contents"]
        assert len(contents) == 1

        parts = contents[0]["parts"]
        assert len(parts) == 2
        assert parts[0]["text"] == "Describe this image:"

        image_payload = parts[1]
        assert "file_data" in image_payload
        file_data = image_payload["file_data"]
        assert file_data["file_uri"] == "https://example.com/image.jpg"
        assert file_data["mime_type"] == "image/jpeg"

    def test_multimodal_content_data_url(self) -> None:
        """Test translation of multimodal content containing a data URL image."""
        text_part = MessageContentPartText(text="Describe this image:")
        image_part = MessageContentPartImage(
            image_url=ImageURL(
                url="data:image/png;base64,SGVsbG8sIHdvcmxkIQ==",
                detail=None,
            )
        )

        request = CanonicalChatRequest(
            model="gemini-1.5-pro-vision",
            messages=[ChatMessage(role="user", content=[text_part, image_part])],
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "contents" in gemini_request
        contents = gemini_request["contents"]
        assert len(contents) == 1

        parts = contents[0]["parts"]
        assert len(parts) == 2
        assert parts[0]["text"] == "Describe this image:"

        inline_payload = parts[1]
        assert "inline_data" in inline_payload
        inline_data = inline_payload["inline_data"]
        assert inline_data["mime_type"] == "image/png"
        assert inline_data["data"] == "SGVsbG8sIHdvcmxkIQ=="

    def test_tool_calling(self) -> None:
        """Test translation of tool calling."""
        # Create a canonical chat request with tools
        messages = [
            ChatMessage(role="user", content="What's the weather in Paris?"),
        ]

        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_weather",
                    description="Get the current weather in a given location",
                    parameters={
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "description": "The temperature unit to use",
                            },
                        },
                        "required": ["location"],
                    },
                ),
            )
        ]

        # Convert tools to dict for CanonicalChatRequest
        tools_dict = [tool.model_dump() for tool in tools]

        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=messages,
            tools=tools_dict,  # type: ignore
            tool_choice="auto",
        )

        # Translate to Gemini format
        gemini_request = Translation.from_domain_to_gemini_request(request)

        # Verify the translation
        assert "contents" in gemini_request
        assert "tools" in gemini_request

        # Check tools
        gemini_tools = gemini_request["tools"]
        assert len(gemini_tools) == 1
        assert "function_declarations" in gemini_tools[0]

        # Check function declaration
        function = gemini_tools[0]["function_declarations"][0]
        assert function["name"] == "get_weather"
        assert function["description"] == "Get the current weather in a given location"
        assert "parameters" in function
        assert function["parameters"]["properties"]["location"]["type"] == "string"


class TestGeminiAPIParityCrossTranslation:
    """Tests for Gemini API parity cross-translation with new parameters."""

    def test_domain_to_gemini_with_candidate_count(self) -> None:
        """Test that n parameter translates to candidateCount in Gemini."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            n=3,
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "generationConfig" in gemini_request
        assert gemini_request["generationConfig"]["candidateCount"] == 3

    def test_domain_to_gemini_with_seed(self) -> None:
        """Test that seed parameter is preserved in Gemini request."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            seed=42,
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "generationConfig" in gemini_request
        assert gemini_request["generationConfig"]["seed"] == 42

    def test_domain_to_gemini_with_penalties(self) -> None:
        """Test that penalty parameters translate to Gemini format."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            presence_penalty=0.5,
            frequency_penalty=0.3,
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "generationConfig" in gemini_request
        assert gemini_request["generationConfig"]["presencePenalty"] == 0.5
        assert gemini_request["generationConfig"]["frequencyPenalty"] == 0.3

    def test_domain_to_gemini_with_logprobs(self) -> None:
        """Test that logprobs parameters translate to Gemini format."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            logprobs=True,
            top_logprobs=5,
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "generationConfig" in gemini_request
        assert gemini_request["generationConfig"]["responseLogprobs"] is True
        assert gemini_request["generationConfig"]["logprobs"] == 5

    def test_domain_to_gemini_with_response_format_json_schema(self) -> None:
        """Test that response_format with json_schema translates correctly."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "test_schema",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "generationConfig" in gemini_request
        gen_config = gemini_request["generationConfig"]
        assert gen_config["responseMimeType"] == "application/json"
        assert "responseSchema" in gen_config
        assert gen_config["responseSchema"]["type"] == "object"

    def test_domain_to_gemini_with_safety_settings_passthrough(self) -> None:
        """Test that safety settings in extra_body are passed through."""
        safety_settings = [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
        ]
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            extra_body={"gemini_safety_settings": safety_settings},
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "safetySettings" in gemini_request
        assert len(gemini_request["safetySettings"]) == 1
        assert (
            gemini_request["safetySettings"][0]["category"]
            == "HARM_CATEGORY_HARASSMENT"
        )

    def test_domain_to_gemini_with_cached_content_passthrough(self) -> None:
        """Test that cached content in extra_body is passed through."""
        request = CanonicalChatRequest(
            model="gemini-1.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            extra_body={"gemini_cached_content": "cachedContents/abc123"},
        )

        gemini_request = Translation.from_domain_to_gemini_request(request)

        assert "cachedContent" in gemini_request
        assert gemini_request["cachedContent"] == "cachedContents/abc123"

    def test_gemini_to_domain_to_gemini_roundtrip(self) -> None:
        """Test that Gemini -> Domain -> Gemini preserves key parameters."""
        from src.core.domain.gemini_translation import (
            gemini_request_to_canonical_request,
        )

        original_request = {
            "model": "gemini-1.5-pro",
            "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.9,
                "topK": 40,
                "maxOutputTokens": 1000,
                "candidateCount": 2,
                "seed": 42,
                "presencePenalty": 0.5,
                "frequencyPenalty": 0.3,
            },
        }

        # Gemini -> Domain
        domain_request = gemini_request_to_canonical_request(original_request)

        # Domain -> Gemini
        gemini_request = Translation.from_domain_to_gemini_request(domain_request)

        # Verify key parameters are preserved
        gen_config = gemini_request["generationConfig"]
        assert gen_config["temperature"] == 0.7
        assert gen_config["topP"] == 0.9
        assert gen_config["topK"] == 40
        assert gen_config["maxOutputTokens"] == 1000
        assert gen_config["candidateCount"] == 2
        assert gen_config["seed"] == 42
        assert gen_config["presencePenalty"] == 0.5
        assert gen_config["frequencyPenalty"] == 0.3


class TestOpenAIToAnthropicTranslation:
    """Tests for OpenAI to Anthropic translation."""

    def test_simple_text_message(self) -> None:
        """Test translation of simple text messages."""
        # Create a canonical chat request with simple text messages
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello, how are you?"),
            ChatMessage(
                role="assistant", content="I'm doing well, how can I help you today?"
            ),
            ChatMessage(role="user", content="Tell me about Python."),
        ]
        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=messages,
            temperature=0.7,
            top_p=0.9,
            max_tokens=1000,
            stop=["END"],
        )

        # Translate to Anthropic format
        anthropic_request = Translation.from_domain_to_anthropic_request(request)

        # Verify the translation
        assert "messages" in anthropic_request
        assert "system" in anthropic_request

        # Check system message
        assert anthropic_request["system"] == "You are a helpful assistant."

        # Check messages (excluding system)
        messages = anthropic_request["messages"]
        assert len(messages) == 3  # Excluding system message

        # Check user messages
        user_messages = [m for m in messages if m["role"] == "user"]
        assert len(user_messages) == 2
        assert user_messages[0]["content"] == "Hello, how are you?"
        assert user_messages[1]["content"] == "Tell me about Python."

        # Check assistant message
        assistant_messages = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_messages) == 1
        assert (
            assistant_messages[0]["content"]
            == "I'm doing well, how can I help you today?"
        )

        # Check parameters
        assert anthropic_request["temperature"] == 0.7
        assert anthropic_request["top_p"] == 0.9
        assert anthropic_request["max_tokens"] == 1000
        assert anthropic_request["stop_sequences"] == ["END"]

    def test_multimodal_content(self) -> None:
        """Test translation of multimodal content."""
        # Create a canonical chat request with multimodal content
        text_part = MessageContentPartText(text="Describe this image:")
        image_part = MessageContentPartImage(
            image_url=ImageURL(url="https://example.com/image.jpg", detail=None)
        )

        messages = [
            ChatMessage(role="user", content=[text_part, image_part]),
        ]
        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=messages,
        )

        # Translate to Anthropic format
        anthropic_request = Translation.from_domain_to_anthropic_request(request)

        # Verify the translation
        assert "messages" in anthropic_request
        messages = anthropic_request["messages"]
        assert len(messages) == 1

        # Check content parts - the implementation now properly handles multimodal content
        content_parts = messages[0]["content"]
        assert len(content_parts) == 2

        # First part should be text
        assert content_parts[0]["type"] == "text"
        assert content_parts[0]["text"] == "Describe this image:"

        # Second part should be the image with URL source
        assert content_parts[1]["type"] == "image"
        assert content_parts[1]["source"]["type"] == "url"
        assert content_parts[1]["source"]["url"] == "https://example.com/image.jpg"

    def test_tool_calling(self) -> None:
        """Test translation of tool calling."""
        # Create a canonical chat request with tools
        messages = [
            ChatMessage(role="user", content="What's the weather in Paris?"),
        ]

        tools = [
            ToolDefinition(
                type="function",
                function=FunctionDefinition(
                    name="get_weather",
                    description="Get the current weather in a given location",
                    parameters={
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {
                                "type": "string",
                                "enum": ["celsius", "fahrenheit"],
                                "description": "The temperature unit to use",
                            },
                        },
                        "required": ["location"],
                    },
                ),
            )
        ]

        # Convert tools to dict for CanonicalChatRequest
        tools_dict = [tool.model_dump() for tool in tools]

        request = CanonicalChatRequest(
            model="claude-3-opus-20240229",
            messages=messages,
            tools=tools_dict,  # type: ignore
            tool_choice="auto",
        )

        # Translate to Anthropic format
        anthropic_request = Translation.from_domain_to_anthropic_request(request)

        # Verify the translation
        assert "messages" in anthropic_request
        assert "tools" in anthropic_request

        # Check tools
        anthropic_tools = anthropic_request["tools"]
        assert len(anthropic_tools) == 1
        assert anthropic_tools[0]["type"] == "function"

        # Check function
        function = anthropic_tools[0]["function"]
        assert function["name"] == "get_weather"
        assert function["description"] == "Get the current weather in a given location"
        assert "parameters" in function
        assert function["parameters"]["properties"]["location"]["type"] == "string"

        # Check tool choice
        assert anthropic_request["tool_choice"] == "auto"


class TestAnthropicToDomainTranslation:
    """Tests for translating Anthropic payloads into canonical requests."""

    def test_includes_system_and_stop_sequences(self) -> None:
        """System prompts and stop sequences should survive canonical translation."""
        payload = {
            "model": "claude-3-sonnet-20240229",
            "system": "Stay in character",
            "max_tokens": 128,
            "stop_sequences": ["CUT"],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe the latest weather update."}
                    ],
                },
                {
                    "role": "assistant",
                    "content": "Sure, let me check that for you.",
                },
            ],
        }

        canonical = Translation.anthropic_to_domain_request(payload)

        assert canonical.model == "claude-3-sonnet-20240229"
        assert canonical.max_tokens == 128
        assert canonical.stop == ["CUT"]

        assert len(canonical.messages) == 3
        assert canonical.messages[0].role == "system"
        assert canonical.messages[0].content == "Stay in character"
        assert canonical.messages[1].role == "user"
        user_content = canonical.messages[1].content
        assert isinstance(user_content, list)
        assert len(user_content) == 1
        first_part = user_content[0]
        if hasattr(first_part, "text"):
            assert first_part.text == "Describe the latest weather update."
        else:
            assert first_part["text"] == "Describe the latest weather update."
        assert canonical.messages[2].role == "assistant"
        assert canonical.messages[2].content == "Sure, let me check that for you."

    def test_tools_and_tool_choice_preserved(self) -> None:
        """Ensure Anthropic tool definitions are available on the canonical request."""

        payload = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Call the tool"}],
            "tools": [
                {
                    "type": "tool",
                    "function": {
                        "name": "lookup",
                        "description": "Lookup information",
                        "input_schema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        }

        canonical = Translation.anthropic_to_domain_request(payload)

        assert canonical.tools is not None
        assert len(canonical.tools) == 1
        first_tool = canonical.tools[0]
        assert first_tool["function"]["name"] == "lookup"  # type: ignore[index]
        assert canonical.tool_choice == {
            "type": "function",
            "function": {"name": "lookup"},
        }
