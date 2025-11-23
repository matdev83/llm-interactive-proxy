from src.core.ports.streaming_contracts import StreamingContent


class TestStreamingErrorLeakage:
    def test_error_chunk_serialization_format(self):
        """
        Test that error chunks are serialized as valid SSE events, not raw JSON.
        The user reported seeing raw JSON like:
        {"choices": [{"delta": {}, "finish_reason": "error"}], "error": ...}

        It should be:
        data: {"choices": [{"delta": {}, "finish_reason": "error"}], "error": ...}

        data: [DONE]
        """
        error_metadata = {
            "finish_reason": "error",
            "error": {
                "type": "AuthenticationError",
                "message": "No auth credentials found",
                "code": "unknown",
                "retryable": False,
                "status_code": 401,
            },
        }

        chunk = StreamingContent(content="", metadata=error_metadata, is_done=True)

        serialized = chunk.to_bytes()
        decoded = serialized.decode("utf-8")

        # This assertion is expected to FAIL before the fix if the bug exists
        assert decoded.startswith(
            "data: "
        ), f"Expected SSE format starting with 'data: ', got: {decoded[:50]}..."
        assert "data: [DONE]" in decoded, "Expected [DONE] sentinel in output"
