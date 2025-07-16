
"""
Unit tests for Gemini API converter functions.
Tests the conversion logic between Gemini and OpenAI formats.
"""
from src.gemini_converters import (
    extract_model_from_gemini_path,
    gemini_to_openai_messages,
    gemini_to_openai_request,
    is_streaming_request,
    openai_models_to_gemini_models,
    openai_to_gemini_contents,
    openai_to_gemini_response,
)
from src.gemini_models import (
    Blob,
    Content,
    FinishReason,
    GenerateContentRequest,
    GenerationConfig,
    Part,
)
from src.models import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatCompletionResponse,
    ChatMessage,
    CompletionUsage,
)


class TestMessageConversion:
    """Test message conversion between formats."""
    
    def test_gemini_to_openai_simple_message(self):
        """Test converting simple Gemini content to OpenAI messages."""
        contents = [
            Content(
                parts=[Part(text="Hello, how are you?")],
                role="user"
            )
        ]
        
        messages = gemini_to_openai_messages(contents)
        
        assert len(messages) == 1
        assert messages[0].role == "user"
        assert messages[0].content == "Hello, how are you?"
    
    def test_gemini_to_openai_model_role(self):
        """Test converting Gemini model role to OpenAI assistant role."""
        contents = [
            Content(
                parts=[Part(text="I'm doing well, thank you!")],
                role="model"
            )
        ]
        
        messages = gemini_to_openai_messages(contents)
        
        assert len(messages) == 1
        assert messages[0].role == "assistant"
        assert messages[0].content == "I'm doing well, thank you!"
    
    def test_gemini_to_openai_multiple_parts(self):
        """Test converting Gemini content with multiple parts."""
        contents = [
            Content(
                parts=[
                    Part(text="Look at this: "),
                    Part(inline_data=Blob(mime_type="image/png", data="base64data")),
                    Part(text=" What do you think?")
                ],
                role="user"
            )
        ]
        
        messages = gemini_to_openai_messages(contents)
        
        assert len(messages) == 1
        assert messages[0].role == "user"
        expected_content = "Look at this: \n[Attachment: image/png]\n What do you think?"
        assert messages[0].content == expected_content
    
    def test_openai_to_gemini_simple_message(self):
        """Test converting OpenAI message to Gemini content."""
        messages = [
            ChatMessage(role="user", content="Hello!")
        ]
        
        contents = openai_to_gemini_contents(messages)
        
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert len(contents[0].parts) == 1
        assert contents[0].parts[0].text == "Hello!"
    
    def test_openai_to_gemini_assistant_role(self):
        """Test converting OpenAI assistant role to Gemini model role."""
        messages = [
            ChatMessage(role="assistant", content="Hello there!")
        ]
        
        contents = openai_to_gemini_contents(messages)
        
        assert len(contents) == 1
        assert contents[0].role == "model"
        assert contents[0].parts[0].text == "Hello there!"
    
    def test_openai_to_gemini_system_role(self):
        """Test converting OpenAI system role to Gemini user role."""
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant.")
        ]
        
        contents = openai_to_gemini_contents(messages)
        
        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].parts[0].text == "You are a helpful assistant."


class TestRequestConversion:
    """Test request conversion between formats."""
    
    def test_gemini_to_openai_basic_request(self):
        """Test converting basic Gemini request to OpenAI format."""
        gemini_request = GenerateContentRequest(
            contents=[
                Content(
                    parts=[Part(text="What is the weather like?")],
                    role="user"
                )
            ],
            tools=None,
            toolConfig=None,
            safetySettings=None,
            systemInstruction=None,
            generationConfig=GenerationConfig(
                stopSequences=None,
                responseMimeType=None,
                responseSchema=None,
                candidateCount=None,
                temperature=0.7,
                maxOutputTokens=100,
                topP=0.9,
                topK=None
            ),
            cachedContent=None
        )
        
        openai_request = gemini_to_openai_request(gemini_request, "test-model")
        
        assert openai_request.model == "test-model"
        assert len(openai_request.messages) == 1
        assert openai_request.messages[0].content == "What is the weather like?"
        assert openai_request.temperature == 0.7
        assert openai_request.max_tokens == 100
        assert openai_request.top_p == 0.9
        assert not openai_request.stream
    
    def test_gemini_to_openai_with_system_instruction(self):
        """Test converting Gemini request with system instruction."""
        gemini_request = GenerateContentRequest(
            contents=[
                Content(
                    parts=[Part(text="What's the capital of France?")],
                    role="user"
                )
            ],
            tools=None,
            toolConfig=None,
            safetySettings=None,
            systemInstruction=Content(
                parts=[Part(text="You are a geography expert.")],
                role="user"
            ),
            generationConfig=None, # No generation config in this test case
            cachedContent=None
        )
        
        openai_request = gemini_to_openai_request(gemini_request, "test-model")
        
        assert len(openai_request.messages) == 2
        assert openai_request.messages[0].role == "system"
        assert openai_request.messages[0].content == "You are a geography expert."
        assert openai_request.messages[1].role == "user"
        assert openai_request.messages[1].content == "What's the capital of France?"


class TestResponseConversion:
    """Test response conversion between formats."""
    
    def test_openai_to_gemini_basic_response(self):
        """Test converting OpenAI response to Gemini format."""
        openai_response = ChatCompletionResponse(
            id="test-id",
            object="chat.completion",
            created=1234567890,
            model="test-model",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="The capital of France is Paris."
                    ),
                    finish_reason="stop"
                )
            ],
            usage=CompletionUsage(
                prompt_tokens=10,
                completion_tokens=8,
                total_tokens=18
            )
        )
        
        gemini_response = openai_to_gemini_response(openai_response)
        
        assert gemini_response.candidates is not None
        assert len(gemini_response.candidates) == 1
        candidate = gemini_response.candidates[0]
        assert candidate.content is not None
        assert candidate.content.role == "model"
        assert len(candidate.content.parts) == 1
        assert candidate.content.parts[0].text == "The capital of France is Paris."
        assert candidate.finish_reason == FinishReason.STOP
        assert candidate.index == 0
        
        assert gemini_response.usage_metadata is not None
        assert gemini_response.usage_metadata.prompt_token_count == 10
        assert gemini_response.usage_metadata.candidates_token_count == 8
        assert gemini_response.usage_metadata.total_token_count == 18
    
    def test_openai_to_gemini_finish_reason_mapping(self):
        """Test finish reason mapping from OpenAI to Gemini."""
        test_cases = [
            ("stop", FinishReason.STOP),
            ("length", FinishReason.MAX_TOKENS),
            ("content_filter", FinishReason.SAFETY),
            (None, None),
            ("tool_calls", FinishReason.TOOL_CALLS),
            ("function_call", FinishReason.FUNCTION_CALL)
        ]
        
        for openai_reason, expected_gemini_reason in test_cases:
            choice = ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content="Test response"
                ),
                finish_reason=openai_reason # Now Optional, so can be None
            )

            openai_response = ChatCompletionResponse(
                id="test-id",
                object="chat.completion",
                created=1234567890,
                model="test-model",
                choices=[choice]
            )
            
            gemini_response = openai_to_gemini_response(openai_response)
            assert gemini_response.candidates is not None
            if expected_gemini_reason is None:
                assert gemini_response.candidates[0].finish_reason is None
            else:
                assert gemini_response.candidates[0].finish_reason == expected_gemini_reason


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_extract_model_from_gemini_path(self):
        """Test extracting model name from Gemini API paths."""
        test_cases = [
            ("/v1beta/models/gemini-pro:generateContent", "gemini-pro"),
            ("/v1beta/models/gemini-1.5-pro:streamGenerateContent", "gemini-1.5-pro"),
            ("/v1beta/models/custom-model:generateContent", "custom-model"),
            ("/invalid/path", "gemini-pro")  # fallback case
        ]
        
        for path, expected_model in test_cases:
            result = extract_model_from_gemini_path(path)
            assert result == expected_model
    
    def test_is_streaming_request(self):
        """Test detecting streaming requests from path."""
        streaming_paths = [
            "/v1beta/models/gemini-pro:streamGenerateContent",
            "/v1beta/models/any-model:streamGenerateContent"
        ]
        
        non_streaming_paths = [
            "/v1beta/models/gemini-pro:generateContent",
            "/v1beta/models/any-model:generateContent",
            "/v1beta/models"
        ]
        
        for path in streaming_paths:
            assert is_streaming_request(path)
        
        for path in non_streaming_paths:
            assert not is_streaming_request(path)
    
    def test_openai_models_to_gemini_models(self):
        """Test converting OpenAI models list to Gemini format."""
        openai_models = [
            {"id": "gpt-4", "object": "model", "owned_by": "openai"},
            {"id": "gpt-3.5-turbo", "object": "model", "owned_by": "openai"}
        ]
        
        gemini_models_response = openai_models_to_gemini_models(openai_models)
        
        assert len(gemini_models_response.models) == 2
        
        model1 = gemini_models_response.models[0]
        assert model1.name == "models/gpt-4"
        assert model1.base_model_id == "gpt-4"
        assert model1.display_name == "Gpt 4"
        assert "generateContent" in model1.supported_generation_methods
        assert "streamGenerateContent" in model1.supported_generation_methods
        assert model1.input_token_limit > 0
        assert model1.output_token_limit > 0
