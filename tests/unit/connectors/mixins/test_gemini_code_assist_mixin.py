"""
Tests for GeminiCodeAssistMixin.

Tests ensure that:
- System messages are correctly converted to user messages.
- Optional fields (tools, toolConfig, safetySettings) are only included if truthy.
"""


from src.connectors.mixins.gemini_code_assist_mixin import GeminiCodeAssistMixin


class MockConnector(GeminiCodeAssistMixin):
    """Mock connector using the mixin."""


def test_build_code_assist_request_excludes_empty_optionals() -> None:
    """Test that empty optional fields are excluded from the request."""
    mixin = MockConnector()
    
    # Input with empty optional fields
    gemini_request = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "generationConfig": {"temperature": 0.5},
        "tools": [],  # Empty list
        "toolConfig": {},  # Empty dict
        "safetySettings": [],  # Empty list
    }
    
    final_contents = gemini_request["contents"]
    
    # Build request
    request = mixin._build_code_assist_request(gemini_request, final_contents)
    
    # Assertions
    assert "contents" in request
    assert "generationConfig" in request
    
    # Verify empty fields are NOT present
    assert "tools" not in request
    assert "toolConfig" not in request
    assert "safetySettings" not in request


def test_build_code_assist_request_includes_non_empty_optionals() -> None:
    """Test that non-empty optional fields are included in the request."""
    mixin = MockConnector()
    
    # Input with populated optional fields
    gemini_request = {
        "contents": [{"role": "user", "parts": [{"text": "Hello"}]}],
        "generationConfig": {"temperature": 0.5},
        "tools": [{"function_declarations": []}],
        "toolConfig": {"function_calling_config": {"mode": "AUTO"}},
        "safetySettings": [{"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}],
    }
    
    final_contents = gemini_request["contents"]
    
    # Build request
    request = mixin._build_code_assist_request(gemini_request, final_contents)
    
    # Assertions
    assert "tools" in request
    assert request["tools"] == gemini_request["tools"]
    
    assert "toolConfig" in request
    assert request["toolConfig"] == gemini_request["toolConfig"]
    
    assert "safetySettings" in request
    assert request["safetySettings"] == gemini_request["safetySettings"]


def test_convert_system_messages_for_code_assist() -> None:
    """Test system message conversion logic (regression test for existing functionality)."""
    mixin = MockConnector()
    
    gemini_request = {
        "contents": [
            {"role": "system", "parts": [{"text": "System prompt"}]},
            {"role": "user", "parts": [{"text": "User prompt"}]},
        ]
    }
    
    converted = mixin._convert_system_messages_for_code_assist(gemini_request)
    
    # Should have 2 messages
    assert len(converted) == 2
    
    # First message should be user role with system content
    assert converted[0]["role"] == "user"
    assert converted[0]["parts"][0]["text"] == "System prompt"
    
    # Second message should be original user prompt
    assert converted[1]["role"] == "user"
    assert converted[1]["parts"][0]["text"] == "User prompt"
