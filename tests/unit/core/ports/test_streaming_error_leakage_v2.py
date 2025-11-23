import pytest
from src.core.common.exceptions import AuthenticationError
from src.core.ports.gemini_normalizer import GeminiStreamNormalizer
from src.core.ports.sse_assembler import SSEAssembler


class TestStreamingErrorLeakageComprehensive:
    @pytest.mark.asyncio
    async def test_streaming_error_pipeline(self):
        """
        Simulate the entire pipeline from normalizer catching an exception
        to assembler yielding bytes.
        """

        # 1. Simulate an exception during streaming
        async def failing_stream():
            yield "some data"
            raise AuthenticationError("No auth credentials found")

        # 2. Use GeminiStreamNormalizer (which uses handle_streaming_error)
        normalizer = GeminiStreamNormalizer()

        # 3. Use SSEAssembler
        assembler = SSEAssembler()

        # 4. Run the pipeline
        output_bytes = []

        # We need to manually drive the pipeline as integrate_streaming_pipeline does
        # But here we just test normalizer -> assembler interaction

        async def run_pipeline():
            # Normalize
            normalized_stream = normalizer.normalize_stream(failing_stream(), "gemini")

            # Assemble
            async for chunk in assembler.assemble_stream(
                normalized_stream, format="sse"
            ):
                output_bytes.append(chunk)

        await run_pipeline()

        # 5. Analyze output
        full_output = b"".join(output_bytes).decode("utf-8")
        print(f"Full Output:\n{full_output}")

        # Check for raw JSON leakage
        lines = full_output.strip().split("\n\n")
        for line in lines:
            if not line.strip():
                continue
            # Every line should start with "data: " (or "event: ", "id: ", etc.)
            # If we find a line that starts with "{", it's a leak.
            assert line.startswith(
                ("data: ", "event: ", ":")
            ), f"Found raw JSON or invalid SSE line: {line}"

        # Check if the error is present and formatted correctly
        assert "No auth credentials found" in full_output
        assert "AuthenticationError" in full_output
