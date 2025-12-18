"""
Usage calculation processor for streaming pipeline.

This module provides a processor that calculates token usage for streaming responses
if the backend does not provide it.
"""

from __future__ import annotations

import logging

from src.core.domain.usage_summary import UsageSummary
from src.core.ports.streaming_contracts import StreamingContent
from src.core.utils.token_count import count_tokens

logger = logging.getLogger(__name__)


class UsageCalculationProcessor:
    """Processor that calculates token usage for streaming responses.

    This processor accumulates the completion content and calculates usage
    when the stream finishes, if usage information is missing.
    """

    def __init__(self, prompt_tokens: int, model_name: str) -> None:
        """Initialize the usage processor.

        Args:
            prompt_tokens: Number of tokens in the prompt
            model_name: Name of the model used (for token counting)
        """
        self.prompt_tokens = prompt_tokens
        self.model_name = model_name
        self.completion_text = ""
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset internal state."""
        self.completion_text = ""

    def reset(self) -> None:
        """Reset the processor state for a new stream."""
        self._reset_state()

    async def process(self, chunk: StreamingContent) -> StreamingContent:
        """Process a streaming chunk.

        Accumulates content and injects usage into the final chunk if missing.

        Args:
            chunk: The streaming chunk to process

        Returns:
            The processed chunk (potentially with usage added)
        """
        # Accumulate content
        if chunk.content:
            if isinstance(chunk.content, str):
                self.completion_text += chunk.content
            elif isinstance(chunk.content, dict):
                # Try to extract text from dict content if possible
                # This depends on the structure, but usually content is str in the pipeline
                pass

        # If this is the final chunk, ensure usage is present
        if chunk.is_done:
            if not chunk.usage:
                # Calculate usage
                completion_tokens = count_tokens(
                    self.completion_text, model=self.model_name
                )
                total_tokens = self.prompt_tokens + completion_tokens

                chunk.usage = UsageSummary.from_dict(
                    {
                        "prompt_tokens": self.prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    }
                )

                logger.debug(
                    "Calculated usage for stream: prompt=%d, completion=%d, total=%d",
                    self.prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )
            else:
                # Usage already present, verify/update if needed?
                # For now, assume backend provided usage is correct or preferred
                pass

        return chunk
