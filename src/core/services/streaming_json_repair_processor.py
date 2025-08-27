from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from src.core.services.json_repair_service import JsonRepairService

logger = logging.getLogger(__name__)


class StreamingJsonRepairProcessor:
    """
    Processes a stream of data, attempting to find, buffer, and repair JSON objects.
    This processor is stateful and designed to be more performant by only
    attempting repairs when a full JSON object is likely present.
    """

    def __init__(
        self,
        repair_service: JsonRepairService,
        buffer_cap_bytes: int,
        strict_mode: bool,
        schema: dict[str, Any] | None = None,  # Added schema parameter
    ) -> None:
        self.repair_service = repair_service
        self.buffer_cap_bytes = buffer_cap_bytes
        self.strict_mode = strict_mode
        self.schema = schema  # Stored schema
        self._reset_state()

    def _reset_state(self) -> None:
        """Resets the processor's state."""
        self.buffer = ""
        self._brace_level = 0
        self._in_string = False
        self._json_started = False

    async def process_stream(
        self,
        stream: AsyncGenerator[str, None],
    ) -> AsyncGenerator[str, None]:
        """
        Processes a stream of data, repairing JSON objects and passing through other text.

        Args:
            stream: An asynchronous generator of data chunks.

        Yields:
            Repaired JSON strings or original data chunks.
        """
        async for chunk in stream:
            for char in chunk:
                if not self._json_started:
                    # Look for the start of a JSON object or array
                    if char == "{" or char == "[":
                        self._json_started = True
                        self.buffer += char
                        self._brace_level += 1
                    else:
                        # Yield non-JSON text until a potential start is found
                        yield char
                else:
                    # Already in a JSON block, process character
                    if char == '"' and (
                        len(self.buffer) == 0 or self.buffer[-1] != "\\"
                    ):  # Handle escaped quotes properly
                        self._in_string = not self._in_string
                    elif not self._in_string:
                        if char == "{" or char == "[":
                            self._brace_level += 1
                        elif char == "}" or char == "]":
                            self._brace_level -= 1
                    self.buffer += char

                    # Check for JSON completion
                    if (
                        self._json_started
                        and self._brace_level == 0
                        and not self._in_string
                    ):
                        repaired_json_obj = (
                            self.repair_service.repair_and_validate_json(
                                self.buffer,
                                strict=self.strict_mode,
                                schema=self.schema,  # Modified
                            )
                        )
                        if repaired_json_obj:
                            yield json.dumps(repaired_json_obj)
                        else:
                            logger.warning(
                                "JSON block detected but failed to repair. Flushing raw buffer."
                            )
                            yield self.buffer
                        self._reset_state()
                        continue  # Move to the next character in the chunk

            # Check buffer capacity after processing the entire chunk
            if self._json_started and len(self.buffer) > self.buffer_cap_bytes:
                # Soft-cap: do not flush; allow continued buffering until JSON completes or stream ends
                logger.warning(
                    "Buffer capacity exceeded during JSON repair. Continuing to buffer until completion."
                )

        # After the loop, flush any remaining buffered content
        if self._json_started and self.buffer:
            logger.debug("Flushing remaining buffer at end of stream.")
            # If the buffer ends with a dangling key/value separator (e.g., '... "key":'),
            # append a JSON null to allow the repairer to complete the structure.
            buf = self.buffer
            if not self._in_string and buf.rstrip().endswith(":"):
                buf = buf + " null"

            repaired_json_obj = self.repair_service.repair_and_validate_json(
                buf, strict=self.strict_mode, schema=self.schema  # Modified
            )
            if repaired_json_obj:
                yield json.dumps(repaired_json_obj)
            else:
                yield self.buffer
            self._reset_state()
