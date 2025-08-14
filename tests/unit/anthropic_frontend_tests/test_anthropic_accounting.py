"""
Unit tests for Anthropic front-end accounting integration.
Tests the token usage tracking and billing info extraction.
"""

from unittest.mock import Mock, patch

from src.anthropic_converters import extract_anthropic_usage
from src.llm_accounting_utils import (
    extract_billing_info_from_headers,
    extract_billing_info_from_response,
)


class TestAnthropicFrontendAccounting:
    """Test suite for Anthropic front-end accounting."""

    def test_extract_billing_info_from_headers_anthropic(self):
        """Test billing info extraction from headers for Anthropic backend."""
        headers = {
            "content-type": "application/json",
            "x-request-id": "req-123",
            "x-anthropic-request-id": "anthropic-456",
        }

        billing_info = extract_billing_info_from_headers(headers, "anthropic")

        assert billing_info["backend"] == "anthropic"
        assert (
            billing_info["provider_info"]["note"]
            == "Anthropic backend - usage info in response only"
        )
        assert billing_info["usage"]["prompt_tokens"] == 0
        assert billing_info["usage"]["completion_tokens"] == 0
        assert billing_info["usage"]["total_tokens"] == 0

    def test_extract_billing_info_from_response_anthropic_dict(self):
        """Test billing info extraction from Anthropic response dictionary."""
        response = {
            "id": "msg-123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            "usage": {"input_tokens": 25, "output_tokens": 15},
        }

        billing_info = extract_billing_info_from_response(response, "anthropic")

        assert billing_info["backend"] == "anthropic"
        assert billing_info["usage"]["prompt_tokens"] == 25
        assert billing_info["usage"]["completion_tokens"] == 15
        assert billing_info["usage"]["total_tokens"] == 40

    def test_extract_billing_info_from_response_anthropic_object(self):
        """Test billing info extraction from Anthropic response object."""
        # Mock Anthropic response object
        mock_usage = Mock()
        mock_usage.input_tokens = 30
        mock_usage.output_tokens = 20

        mock_response = Mock()
        mock_response.usage = mock_usage

        billing_info = extract_billing_info_from_response(mock_response, "anthropic")

        assert billing_info["backend"] == "anthropic"
        assert billing_info["usage"]["prompt_tokens"] == 30
        assert billing_info["usage"]["completion_tokens"] == 20
        assert billing_info["usage"]["total_tokens"] == 50

    def test_extract_billing_info_from_response_anthropic_no_usage(self):
        """Test billing info extraction when no usage info is available."""
        response = {
            "id": "msg-123",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello!"}],
            # No usage field
        }

        billing_info = extract_billing_info_from_response(response, "anthropic")

        assert billing_info["backend"] == "anthropic"
        assert billing_info["usage"]["prompt_tokens"] == 0
        assert billing_info["usage"]["completion_tokens"] == 0
        assert billing_info["usage"]["total_tokens"] == 0

    def test_extract_anthropic_usage_from_dict(self):
        """Test extract_anthropic_usage function with dictionary."""
        response = {"usage": {"input_tokens": 45, "output_tokens": 35}}

        usage = extract_anthropic_usage(response)

        assert usage["input_tokens"] == 45
        assert usage["output_tokens"] == 35
        assert usage["total_tokens"] == 80

    def test_extract_anthropic_usage_from_object(self):
        """Test extract_anthropic_usage function with object."""
        mock_usage = Mock()
        mock_usage.input_tokens = 60
        mock_usage.output_tokens = 40

        mock_response = Mock()
        mock_response.usage = mock_usage

        usage = extract_anthropic_usage(mock_response)

        assert usage["input_tokens"] == 60
        assert usage["output_tokens"] == 40
        assert usage["total_tokens"] == 100

    def test_extract_anthropic_usage_empty_response(self):
        """Test extract_anthropic_usage function with empty response."""
        usage = extract_anthropic_usage({})

        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_extract_anthropic_usage_invalid_response(self):
        """Test extract_anthropic_usage function with invalid response."""
        usage = extract_anthropic_usage(None)

        assert usage["input_tokens"] == 0
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 0

    def test_extract_anthropic_usage_partial_data(self):
        """Test extract_anthropic_usage function with partial data."""
        response = {
            "usage": {
                "input_tokens": 25
                # Missing output_tokens
            }
        }

        usage = extract_anthropic_usage(response)

        assert usage["input_tokens"] == 25
        assert usage["output_tokens"] == 0
        assert usage["total_tokens"] == 25

    @patch("src.anthropic_converters.extract_anthropic_usage")
    def test_billing_info_calls_extract_usage(self, mock_extract_usage):
        """Test that billing info extraction calls extract_anthropic_usage."""
        mock_extract_usage.return_value = {
            "input_tokens": 50,
            "output_tokens": 30,
            "total_tokens": 80,
        }

        response = {"some": "data"}
        billing_info = extract_billing_info_from_response(response, "anthropic")

        mock_extract_usage.assert_called_once_with(response)
        assert billing_info["usage"]["prompt_tokens"] == 50
        assert billing_info["usage"]["completion_tokens"] == 30
        assert billing_info["usage"]["total_tokens"] == 80

    def test_billing_info_structure_anthropic(self):
        """Test the structure of billing info for Anthropic."""
        headers: dict[str, str] = {}
        response = {"usage": {"input_tokens": 10, "output_tokens": 15}}

        header_billing = extract_billing_info_from_headers(headers, "anthropic")
        response_billing = extract_billing_info_from_response(response, "anthropic")

        # Check header billing structure
        assert "backend" in header_billing
        assert "usage" in header_billing
        assert "provider_info" in header_billing
        assert "cost" in header_billing

        # Check response billing structure
        assert "backend" in response_billing
        assert "usage" in response_billing
        assert "provider_info" in response_billing
        assert "cost" in response_billing

        # Check usage fields
        for billing in [header_billing, response_billing]:
            assert "prompt_tokens" in billing["usage"]
            assert "completion_tokens" in billing["usage"]
            assert "total_tokens" in billing["usage"]

    def test_anthropic_vs_other_backends(self):
        """Test that Anthropic billing differs from other backends."""
        headers = {"x-request-id": "123"}
        response = {"usage": {"input_tokens": 10, "output_tokens": 5}}

        # Anthropic billing
        anthropic_header = extract_billing_info_from_headers(headers, "anthropic")
        anthropic_response = extract_billing_info_from_response(response, "anthropic")

        # OpenRouter billing for comparison
        openrouter_header = extract_billing_info_from_headers(headers, "openrouter")
        extract_billing_info_from_response(response, "openrouter")

        # Should have different provider info
        assert anthropic_header["provider_info"]["note"] != openrouter_header[
            "provider_info"
        ].get("note", "")

        # Anthropic should extract usage from response, OpenRouter might not
        assert anthropic_response["usage"]["prompt_tokens"] == 10
        assert anthropic_response["usage"]["completion_tokens"] == 5

    def test_streaming_response_billing(self):
        """Test billing info extraction from streaming responses."""
        from starlette.responses import StreamingResponse

        async def generate():
            yield b"data: chunk1\n\n"
            yield b"data: chunk2\n\n"

        streaming_response = StreamingResponse(generate())

        # Should handle streaming responses gracefully
        billing_info = extract_billing_info_from_response(
            streaming_response, "anthropic"
        )

        assert billing_info["backend"] == "anthropic"
        # Usage should be 0 for streaming since we can't extract from the stream
        assert billing_info["usage"]["prompt_tokens"] == 0
        assert billing_info["usage"]["completion_tokens"] == 0

    def test_cost_calculation_placeholder(self):
        """Test cost calculation (placeholder for future implementation)."""
        response = {"usage": {"input_tokens": 100, "output_tokens": 50}}

        billing_info = extract_billing_info_from_response(response, "anthropic")

        # Cost should be 0.0 for now (not implemented)
        assert billing_info["cost"] == 0.0

        # Future implementation could calculate based on Anthropic pricing:
        # Claude-3 Sonnet: $3/1M input tokens, $15/1M output tokens
        # Expected cost for this example: (100 * 3 + 50 * 15) / 1_000_000 = 0.00105
