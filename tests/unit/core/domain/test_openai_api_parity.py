"""
Tests for OpenAI Chat Completions API parity features.

This test module validates that all OpenAI API features added for parity
are properly supported in domain models, translation, and connectors.
"""

from __future__ import annotations

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalStreamChunk,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FunctionDefinition,
    InputAudio,
    MessageContentPartAudio,
    MessageContentPartText,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
    ToolDefinition,
)


class TestPhase1CoreCompatibility:
    """Tests for Phase 1: Core Compatibility features."""

    def test_max_completion_tokens_in_chat_request(self):
        """Test that max_completion_tokens is supported in ChatRequest."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=1000,
        )
        assert request.max_completion_tokens == 1000
        assert request.max_tokens is None  # Deprecated field

    def test_max_completion_tokens_coexists_with_max_tokens(self):
        """Test that both max_completion_tokens and max_tokens can be set."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=500,  # Deprecated
            max_completion_tokens=1000,  # New standard
        )
        assert request.max_tokens == 500
        assert request.max_completion_tokens == 1000

    def test_logprobs_in_chat_request(self):
        """Test that logprobs parameter is supported in ChatRequest."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            logprobs=True,
        )
        assert request.logprobs is True

    def test_top_logprobs_in_chat_request(self):
        """Test that top_logprobs parameter is supported in ChatRequest."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            logprobs=True,
            top_logprobs=5,
        )
        assert request.top_logprobs == 5

    def test_parallel_tool_calls_in_chat_request(self):
        """Test that parallel_tool_calls parameter is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            parallel_tool_calls=True,
        )
        assert request.parallel_tool_calls is True

    def test_strict_in_function_definition(self):
        """Test that strict mode is supported in FunctionDefinition."""
        func_def = FunctionDefinition(
            name="get_weather",
            description="Get the weather",
            parameters={"type": "object", "properties": {}},
            strict=True,
        )
        assert func_def.strict is True

    def test_strict_in_tool_definition(self):
        """Test that strict mode works through ToolDefinition."""
        tool = ToolDefinition(
            type="function",
            function=FunctionDefinition(
                name="get_weather",
                description="Get the weather",
                strict=True,
            ),
        )
        assert tool.function.strict is True

    def test_logprobs_in_chat_completion_choice(self):
        """Test that logprobs field is supported in ChatCompletionChoice."""
        choice = ChatCompletionChoice(
            index=0,
            message=ChatCompletionChoiceMessage(role="assistant", content="Hi"),
            finish_reason="stop",
            logprobs={"content": [{"token": "Hi", "logprob": -0.5}]},
        )
        assert choice.logprobs is not None
        assert "content" in choice.logprobs

    def test_logprobs_in_streaming_choice(self):
        """Test that logprobs field is supported in StreamingChatCompletionChoice."""
        delta = StreamingChatCompletionChoiceDelta(content="Hi")
        choice = StreamingChatCompletionChoice(
            index=0,
            delta=delta,
            finish_reason=None,
            logprobs={"content": [{"token": "Hi", "logprob": -0.5}]},
        )
        assert choice.logprobs is not None


class TestPhase2ServiceFeatures:
    """Tests for Phase 2: Service Features."""

    def test_service_tier_in_chat_request(self):
        """Test that service_tier parameter is supported in ChatRequest."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            service_tier="default",
        )
        assert request.service_tier == "default"

    def test_service_tier_in_chat_response(self):
        """Test that service_tier field is supported in ChatResponse."""
        response = ChatResponse(
            id="chatcmpl-123",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(role="assistant", content="Hi"),
                    finish_reason="stop",
                )
            ],
            service_tier="default",
        )
        assert response.service_tier == "default"

    def test_response_format_in_chat_request(self):
        """Test that response_format is a first-class field in ChatRequest."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format={"type": "json_object"},
        )
        assert request.response_format == {"type": "json_object"}

    def test_response_format_json_schema(self):
        """Test that response_format supports json_schema type."""
        schema = {
            "type": "json_schema",
            "json_schema": {
                "name": "person",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                },
            },
        }
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format=schema,
        )
        assert request.response_format["type"] == "json_schema"


class TestPhase3AdvancedFeatures:
    """Tests for Phase 3: Advanced Features."""

    def test_store_in_chat_request(self):
        """Test that store parameter is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            store=True,
        )
        assert request.store is True

    def test_request_metadata_in_chat_request(self):
        """Test that request_metadata parameter is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            request_metadata={"user_id": "123", "session": "abc"},
        )
        assert request.request_metadata == {"user_id": "123", "session": "abc"}

    def test_prediction_in_chat_request(self):
        """Test that prediction parameter is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            prediction={"type": "content", "content": "Expected output"},
        )
        assert request.prediction["type"] == "content"

    def test_modalities_in_chat_request(self):
        """Test that modalities parameter is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            modalities=["text", "audio"],
        )
        assert "audio" in request.modalities

    def test_audio_config_in_chat_request(self):
        """Test that audio output config is supported."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            audio={"voice": "alloy", "format": "mp3"},
        )
        assert request.audio["voice"] == "alloy"

    def test_refusal_in_chat_completion_message(self):
        """Test that refusal field is supported in response messages."""
        message = ChatCompletionChoiceMessage(
            role="assistant",
            content=None,
            refusal="I cannot help with that request.",
        )
        assert message.refusal == "I cannot help with that request."

    def test_annotations_in_chat_completion_message(self):
        """Test that annotations field is supported in response messages."""
        annotations = [
            {"type": "url_citation", "url": "https://example.com", "text": "source"}
        ]
        message = ChatCompletionChoiceMessage(
            role="assistant",
            content="Based on the source...",
            annotations=annotations,
        )
        assert len(message.annotations) == 1
        assert message.annotations[0]["type"] == "url_citation"


class TestAudioInputContent:
    """Tests for audio input content in multimodal messages."""

    def test_input_audio_model(self):
        """Test InputAudio model creation."""
        audio = InputAudio(
            data="base64encodedaudiodata",
            format="wav",
        )
        assert audio.data == "base64encodedaudiodata"
        assert audio.format == "wav"

    def test_message_content_part_audio(self):
        """Test MessageContentPartAudio model creation."""
        audio_part = MessageContentPartAudio(
            type="input_audio",
            input_audio=InputAudio(data="audiodata", format="mp3"),
        )
        assert audio_part.type == "input_audio"
        assert audio_part.input_audio.format == "mp3"

    def test_chat_message_with_audio_content(self):
        """Test ChatMessage can contain audio content parts."""
        audio_part = MessageContentPartAudio(
            type="input_audio",
            input_audio=InputAudio(data="audiodata", format="wav"),
        )
        text_part = MessageContentPartText(type="text", text="Transcribe this audio")

        message = ChatMessage(role="user", content=[text_part, audio_part])
        assert len(message.content) == 2


class TestTranslationOpenAIRequest:
    """Tests for OpenAI request translation with new parameters."""

    def test_openai_translation_includes_max_completion_tokens(self):
        """Test that OpenAI translation includes max_completion_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=1000,
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("max_completion_tokens") == 1000

    def test_openai_translation_includes_logprobs(self):
        """Test that OpenAI translation includes logprobs parameters."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            logprobs=True,
            top_logprobs=5,
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("logprobs") is True
        assert payload.get("top_logprobs") == 5

    def test_openai_translation_includes_parallel_tool_calls(self):
        """Test that OpenAI translation includes parallel_tool_calls."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            parallel_tool_calls=True,
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("parallel_tool_calls") is True

    def test_openai_translation_includes_service_tier(self):
        """Test that OpenAI translation includes service_tier."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            service_tier="default",
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("service_tier") == "default"

    def test_openai_translation_includes_response_format(self):
        """Test that OpenAI translation includes response_format."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format={"type": "json_object"},
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("response_format") == {"type": "json_object"}

    def test_openai_translation_includes_store(self):
        """Test that OpenAI translation includes store parameter."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            store=True,
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("store") is True

    def test_openai_translation_includes_metadata(self):
        """Test that OpenAI translation includes metadata parameter."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            request_metadata={"user": "test"},
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("metadata") == {"user": "test"}

    def test_openai_translation_includes_modalities(self):
        """Test that OpenAI translation includes modalities parameter."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            modalities=["text", "audio"],
        )

        payload = Translation.from_domain_to_openai_request(request)
        assert payload.get("modalities") == ["text", "audio"]


class TestTranslationGeminiRequest:
    """Tests for Gemini request translation with new parameters."""

    def test_gemini_translation_uses_max_completion_tokens(self):
        """Test that Gemini translation uses max_completion_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=1000,
        )

        payload = Translation.from_domain_to_gemini_request(request)
        assert payload["generationConfig"]["maxOutputTokens"] == 1000

    def test_gemini_translation_prefers_max_completion_tokens_over_max_tokens(self):
        """Test that Gemini translation prefers max_completion_tokens over max_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=500,
            max_completion_tokens=1000,
        )

        payload = Translation.from_domain_to_gemini_request(request)
        # Should use max_completion_tokens (1000) not max_tokens (500)
        assert payload["generationConfig"]["maxOutputTokens"] == 1000

    def test_gemini_translation_falls_back_to_max_tokens(self):
        """Test that Gemini translation falls back to max_tokens if max_completion_tokens not set."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=500,
        )

        payload = Translation.from_domain_to_gemini_request(request)
        assert payload["generationConfig"]["maxOutputTokens"] == 500

    def test_gemini_translation_handles_response_format_json_schema(self):
        """Test that Gemini translation handles response_format with json_schema."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="gemini-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        )

        payload = Translation.from_domain_to_gemini_request(request)
        gen_config = payload["generationConfig"]
        assert gen_config.get("responseMimeType") == "application/json"
        assert "responseSchema" in gen_config


class TestTranslationAnthropicRequest:
    """Tests for Anthropic request translation with new parameters."""

    def test_anthropic_translation_uses_max_completion_tokens(self):
        """Test that Anthropic translation uses max_completion_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="claude-3-opus",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=1000,
        )

        payload = Translation.from_domain_to_anthropic_request(request)
        assert payload["max_tokens"] == 1000

    def test_anthropic_translation_prefers_max_completion_tokens(self):
        """Test that Anthropic translation prefers max_completion_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="claude-3-opus",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=500,
            max_completion_tokens=1000,
        )

        payload = Translation.from_domain_to_anthropic_request(request)
        assert payload["max_tokens"] == 1000

    def test_anthropic_translation_falls_back_to_max_tokens(self):
        """Test that Anthropic translation falls back to max_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="claude-3-opus",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=500,
        )

        payload = Translation.from_domain_to_anthropic_request(request)
        assert payload["max_tokens"] == 500

    def test_anthropic_translation_defaults_max_tokens(self):
        """Test that Anthropic translation has default max_tokens."""
        from src.core.domain.translation import Translation

        request = CanonicalChatRequest(
            model="claude-3-opus",
            messages=[ChatMessage(role="user", content="Hello")],
        )

        payload = Translation.from_domain_to_anthropic_request(request)
        assert payload["max_tokens"] == 1024  # Default


class TestTranslationOpenAIResponse:
    """Tests for OpenAI response translation preserving new fields."""

    def test_openai_response_preserves_service_tier(self):
        """Test that OpenAI response translation preserves service_tier."""
        from src.core.domain.translation import Translation

        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "service_tier": "default",
        }

        result = Translation.openai_to_domain_response(response)
        assert result.service_tier == "default"

    def test_openai_response_preserves_logprobs(self):
        """Test that OpenAI response translation preserves logprobs in choices."""
        from src.core.domain.translation import Translation

        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hi"},
                    "finish_reason": "stop",
                    "logprobs": {"content": [{"token": "Hi", "logprob": -0.5}]},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        result = Translation.openai_to_domain_response(response)
        assert result.choices[0].logprobs is not None
        assert "content" in result.choices[0].logprobs

    def test_openai_response_preserves_refusal(self):
        """Test that OpenAI response translation preserves refusal in message."""
        from src.core.domain.translation import Translation

        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "refusal": "I cannot help with that.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        result = Translation.openai_to_domain_response(response)
        assert result.choices[0].message.refusal == "I cannot help with that."

    def test_openai_response_preserves_annotations(self):
        """Test that OpenAI response translation preserves annotations."""
        from src.core.domain.translation import Translation

        response = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Based on the source...",
                        "annotations": [
                            {"type": "url_citation", "url": "https://example.com"}
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        result = Translation.openai_to_domain_response(response)
        assert result.choices[0].message.annotations is not None
        assert len(result.choices[0].message.annotations) == 1


class TestUsageDetailsPreservation:
    """Tests for usage details preservation (prompt_tokens_details, completion_tokens_details)."""

    def test_usage_preserves_prompt_tokens_details(self):
        """Test that usage translation preserves prompt_tokens_details."""
        from src.core.domain.translation import Translation

        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "prompt_tokens_details": {"cached_tokens": 20, "audio_tokens": 5},
        }

        result = Translation._normalize_usage_metadata(usage, "openai")
        assert "prompt_tokens_details" in result
        assert result["prompt_tokens_details"]["cached_tokens"] == 20

    def test_usage_preserves_completion_tokens_details(self):
        """Test that usage translation preserves completion_tokens_details."""
        from src.core.domain.translation import Translation

        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 30, "audio_tokens": 10},
        }

        result = Translation._normalize_usage_metadata(usage, "openai")
        assert "completion_tokens_details" in result
        assert result["completion_tokens_details"]["reasoning_tokens"] == 30


class TestStreamingChunkTranslation:
    """Tests for streaming chunk translation with new fields."""

    def test_streaming_chunk_preserves_logprobs(self):
        """Test that streaming chunk translation preserves logprobs."""
        from src.core.domain.translation import Translation

        chunk = {
            "id": "chatcmpl-123",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Hi"},
                    "finish_reason": None,
                    "logprobs": {"content": [{"token": "Hi", "logprob": -0.5}]},
                }
            ],
        }

        result = Translation.openai_to_domain_stream_chunk(chunk)
        assert isinstance(result, CanonicalStreamChunk)
        assert result.choices[0].logprobs is not None


class TestModelSerialization:
    """Tests for model serialization to ensure new fields are included."""

    def test_chat_request_serialization_includes_new_fields(self):
        """Test that ChatRequest serialization includes all new fields."""
        request = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="Hello")],
            max_completion_tokens=1000,
            logprobs=True,
            top_logprobs=5,
            parallel_tool_calls=True,
            response_format={"type": "json_object"},
            service_tier="default",
            store=True,
            request_metadata={"key": "value"},
            modalities=["text"],
        )

        data = request.model_dump(exclude_none=True)
        assert data["max_completion_tokens"] == 1000
        assert data["logprobs"] is True
        assert data["top_logprobs"] == 5
        assert data["parallel_tool_calls"] is True
        assert data["response_format"] == {"type": "json_object"}
        assert data["service_tier"] == "default"
        assert data["store"] is True
        assert data["request_metadata"] == {"key": "value"}
        assert data["modalities"] == ["text"]

    def test_chat_response_serialization_includes_service_tier(self):
        """Test that ChatResponse serialization includes service_tier."""
        response = ChatResponse(
            id="chatcmpl-123",
            created=1234567890,
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(role="assistant", content="Hi"),
                    finish_reason="stop",
                    logprobs={"content": []},
                )
            ],
            service_tier="default",
        )

        data = response.model_dump(exclude_none=True)
        assert data["service_tier"] == "default"
        assert data["choices"][0]["logprobs"] == {"content": []}

    def test_message_serialization_includes_refusal_and_annotations(self):
        """Test that message serialization includes refusal and annotations."""
        message = ChatCompletionChoiceMessage(
            role="assistant",
            content="Response",
            refusal=None,
            annotations=[{"type": "citation"}],
        )

        data = message.model_dump(exclude_none=True)
        assert data["annotations"] == [{"type": "citation"}]
        # refusal should be excluded when None
        assert "refusal" not in data
