"""Integration tests for OpenAI Responses API translation scenarios.

This module tests the comprehensive translation scenarios mentioned in task 7.2:
- OpenAI Responses API frontend <-> OpenAI Responses API backend (no API/protocol translations needed)
- OpenAI Responses API frontend <-> OpenAI Messages API backend
- Anthropic API frontend <-> OpenAI Responses API backend
- Gemini API frontend <-> OpenAI Responses API backend
"""

import pytest
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
)
from src.core.services.translation_service import TranslationService


class TestResponsesAPITranslationScenarios:
    """Test comprehensive translation scenarios for Responses API."""

    @pytest.fixture
    def translation_service(self):
        """Create a translation service."""
        return TranslationService()

    @pytest.fixture
    def sample_json_schema(self):
        """Sample JSON schema for testing."""
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "email": {"type": "string", "format": "email"},
            },
            "required": ["name", "age"],
        }

    @pytest.fixture
    def sample_responses_request(self, sample_json_schema):
        """Sample Responses API request."""
        return {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person profile"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "description": "A person's profile information",
                    "schema": sample_json_schema,
                    "strict": True,
                },
            },
            "max_tokens": 150,
            "temperature": 0.7,
        }

    @pytest.fixture
    def sample_anthropic_request(self):
        """Sample Anthropic API request."""
        return {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Generate a person profile"}],
            "max_tokens": 150,
            "temperature": 0.7,
        }

    @pytest.fixture
    def sample_gemini_request(self):
        """Sample Gemini API request."""
        return {
            "contents": [
                {"role": "user", "parts": [{"text": "Generate a person profile"}]}
            ],
            "generationConfig": {"maxOutputTokens": 150, "temperature": 0.7},
        }

    def test_responses_frontend_to_responses_backend_no_translation(
        self, translation_service, sample_responses_request
    ):
        """Test OpenAI Responses API frontend <-> OpenAI Responses API backend (no translation needed)."""
        # Convert Responses API request to domain
        domain_request = translation_service.to_domain_request(
            sample_responses_request, "responses"
        )

        # Convert domain request to Responses API backend format
        backend_request = translation_service.from_domain_request(
            domain_request, "openai-responses"
        )

        # Verify the structure is preserved
        assert backend_request["model"] == sample_responses_request["model"]
        assert backend_request["messages"] == sample_responses_request["messages"]
        assert (
            backend_request["response_format"]
            == sample_responses_request["response_format"]
        )
        assert backend_request["max_tokens"] == sample_responses_request["max_tokens"]
        assert backend_request["temperature"] == sample_responses_request["temperature"]

    def test_responses_frontend_to_openai_messages_backend(
        self, translation_service, sample_responses_request
    ):
        """Test OpenAI Responses API frontend <-> OpenAI Messages API backend."""
        # Convert Responses API request to domain
        domain_request = translation_service.to_domain_request(
            sample_responses_request, "responses"
        )

        # Convert domain request to OpenAI Messages API backend format
        backend_request = translation_service.from_domain_request(
            domain_request, "openai"
        )

        # Verify the basic structure
        assert backend_request["model"] == sample_responses_request["model"]
        assert backend_request["messages"] == sample_responses_request["messages"]
        assert backend_request["max_tokens"] == sample_responses_request["max_tokens"]
        assert backend_request["temperature"] == sample_responses_request["temperature"]

        # Verify response_format is preserved in the request for structured output
        assert "response_format" in backend_request
        assert backend_request["response_format"]["type"] == "json_schema"

    def test_anthropic_frontend_to_responses_backend(
        self, translation_service, sample_anthropic_request, sample_json_schema
    ):
        """Test Anthropic API frontend <-> OpenAI Responses API backend."""
        # Create an Anthropic request object (not dict) for proper translation

        # Create the domain request with structured output requirements
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "description": "A person's profile information",
                    "schema": sample_json_schema,
                    "strict": True,
                },
            }
        }

        domain_request = CanonicalChatRequest(
            model=sample_anthropic_request["model"],
            messages=[
                ChatMessage(**msg) for msg in sample_anthropic_request["messages"]
            ],
            max_tokens=sample_anthropic_request["max_tokens"],
            temperature=sample_anthropic_request["temperature"],
            extra_body=extra_body,
        )

        # Convert domain request to Responses API backend format
        backend_request = translation_service.from_domain_request(
            domain_request, "openai-responses"
        )

        # Verify the translation
        assert backend_request["model"] == sample_anthropic_request["model"]
        assert len(backend_request["messages"]) == len(
            sample_anthropic_request["messages"]
        )
        assert backend_request["max_tokens"] == sample_anthropic_request["max_tokens"]
        assert backend_request["temperature"] == sample_anthropic_request["temperature"]

        # Verify structured output format is preserved
        assert "response_format" in backend_request
        assert backend_request["response_format"]["type"] == "json_schema"
        assert (
            backend_request["response_format"]["json_schema"]["name"]
            == "person_profile"
        )

    def test_gemini_frontend_to_responses_backend(
        self, translation_service, sample_gemini_request, sample_json_schema
    ):
        """Test Gemini API frontend <-> OpenAI Responses API backend."""
        # Convert Gemini request to domain first
        domain_request = translation_service.to_domain_request(
            sample_gemini_request, "gemini"
        )

        # Create a new domain request with structured output requirements
        # (since the original is frozen)
        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "description": "A person's profile information",
                    "schema": sample_json_schema,
                    "strict": True,
                },
            }
        }

        domain_request = CanonicalChatRequest(
            model=domain_request.model,
            messages=domain_request.messages,
            max_tokens=domain_request.max_tokens,
            temperature=domain_request.temperature,
            extra_body=extra_body,
        )

        # Convert domain request to Responses API backend format
        backend_request = translation_service.from_domain_request(
            domain_request, "openai-responses"
        )

        # Verify the translation
        assert "model" in backend_request  # Gemini model gets translated
        assert len(backend_request["messages"]) >= 1
        assert backend_request["messages"][0]["role"] == "user"
        assert "Generate a person profile" in backend_request["messages"][0]["content"]

        # Verify structured output format is preserved
        assert "response_format" in backend_request
        assert backend_request["response_format"]["type"] == "json_schema"
        assert (
            backend_request["response_format"]["json_schema"]["name"]
            == "person_profile"
        )

    def test_response_translation_from_responses_backend(self, translation_service):
        """Test translating responses from OpenAI Responses API backend to different frontend formats."""
        # Sample Responses API backend response
        responses_backend_response = {
            "id": "resp-123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"name": "John Doe", "age": 30, "email": "john@example.com"}',
                        "parsed": {
                            "name": "John Doe",
                            "age": 30,
                            "email": "john@example.com",
                        },
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40},
        }

        # Convert to domain response
        domain_response = translation_service.to_domain_response(
            responses_backend_response, "openai-responses"
        )

        # Test conversion to different frontend formats

        # 1. To OpenAI Messages API format
        openai_response = translation_service.from_domain_response(
            domain_response, "openai"
        )
        assert openai_response["object"] == "chat.completion"
        assert openai_response["choices"][0]["message"]["role"] == "assistant"
        assert "John Doe" in openai_response["choices"][0]["message"]["content"]

        # 2. To Anthropic format
        anthropic_response = translation_service.from_domain_response(
            domain_response, "anthropic"
        )
        assert anthropic_response["type"] == "completion"
        assert anthropic_response["role"] == "assistant"
        assert "John Doe" in anthropic_response["content"]

        # 3. To Gemini format
        gemini_response = translation_service.from_domain_response(
            domain_response, "gemini"
        )
        assert "candidates" in gemini_response
        assert len(gemini_response["candidates"]) == 1
        assert (
            "John Doe"
            in gemini_response["candidates"][0]["content"]["parts"][0]["text"]
        )

        # 4. Back to Responses API format
        responses_response = translation_service.from_domain_response(
            domain_response, "openai-responses"
        )
        assert responses_response["object"] == "response"
        assert responses_response["choices"][0]["message"]["parsed"] is not None

    def test_structured_output_preservation_across_translations(
        self, translation_service, sample_json_schema
    ):
        """Test that structured output requirements are preserved across different translation paths."""
        # Start with a Responses API request
        original_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate data"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_schema",
                    "schema": sample_json_schema,
                    "strict": True,
                },
            },
        }

        # Convert through the translation pipeline
        domain_request = translation_service.to_domain_request(
            original_request, "responses"
        )

        # Test different backend translations preserve structured output
        backends = ["openai", "openai-responses"]

        for backend in backends:
            backend_request = translation_service.from_domain_request(
                domain_request, backend
            )

            # Verify structured output is preserved
            assert "response_format" in backend_request
            response_format = backend_request["response_format"]
            assert response_format["type"] == "json_schema"

            if backend == "openai-responses":
                # For Responses API backend, full structure should be preserved
                assert "json_schema" in response_format
                assert response_format["json_schema"]["name"] == "test_schema"
                assert response_format["json_schema"]["schema"] == sample_json_schema

    def test_error_handling_in_translation_scenarios(self, translation_service):
        """Test error handling in various translation scenarios."""
        # Test invalid Responses API request
        invalid_request = {
            "model": "gpt-4",
            "messages": [],  # Empty messages should cause validation error
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test", "schema": {"type": "object"}},
            },
        }

        with pytest.raises(ValueError, match="At least one message is required"):
            translation_service.to_domain_request(invalid_request, "responses")

        # Test invalid JSON schema
        invalid_schema_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test",
                    "schema": {},  # Missing required 'type' field
                },
            },
        }

        with pytest.raises(ValueError, match="Schema must have a 'type' field"):
            translation_service.to_domain_request(invalid_schema_request, "responses")

    def test_round_trip_translation_consistency(
        self, translation_service, sample_responses_request
    ):
        """Test that round-trip translations maintain consistency."""
        # Original -> Domain -> Backend -> Domain -> Frontend

        # Step 1: Responses API -> Domain
        domain_request = translation_service.to_domain_request(
            sample_responses_request, "responses"
        )

        # Step 2: Domain -> Responses API Backend
        backend_request = translation_service.from_domain_request(
            domain_request, "openai-responses"
        )

        # Step 3: Backend -> Domain (simulate backend response processing)
        domain_request_2 = translation_service.to_domain_request(
            backend_request, "responses"
        )

        # Verify consistency
        assert domain_request.model == domain_request_2.model
        assert len(domain_request.messages) == len(domain_request_2.messages)
        assert domain_request.max_tokens == domain_request_2.max_tokens
        assert domain_request.temperature == domain_request_2.temperature

        # Verify structured output is preserved
        assert domain_request.extra_body is not None
        assert domain_request_2.extra_body is not None
        assert "response_format" in domain_request.extra_body
        assert "response_format" in domain_request_2.extra_body
