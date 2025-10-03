import json
import logging
from typing import Any, cast

from src.core.domain.chat import ChatResponse
from src.core.interfaces.response_parser_interface import IResponseParser

logger = logging.getLogger(__name__)


class ParsingError(Exception):
    """Custom exception for response parsing errors."""


class ResponseParser(IResponseParser):
    """
    Parses various response formats into a standardized structure.
    """

    def parse_response(
        self,
        raw_response: ChatResponse | dict[str, Any] | str | None,
        is_streaming: bool = False,
    ) -> dict[str, Any]:
        """
        Parses a raw response into a standardized dictionary format.

        Args:
            raw_response: The raw response, which can be a ChatResponse object,
                          a dictionary, or a string.
            is_streaming: A boolean indicating if the response is part of a streaming sequence.

        Returns:
            A dictionary containing the parsed response data, including content,
            usage, and other metadata.
        """
        content = ""
        usage = None
        metadata: dict[str, Any] = {}

        if isinstance(raw_response, ChatResponse):
            metadata["model"] = raw_response.model
            metadata["id"] = raw_response.id
            from datetime import datetime

            dt_object = datetime.utcfromtimestamp(raw_response.created)
            metadata["created"] = dt_object.isoformat(timespec="seconds")

            if raw_response.choices:
                choice = raw_response.choices[0]
                if hasattr(choice, "message"):
                    if hasattr(choice.message, "content"):
                        content = choice.message.content or ""
                    if (
                        hasattr(choice.message, "tool_calls")
                        and choice.message.tool_calls
                    ):
                        metadata["tool_calls"] = [
                            tc.model_dump() for tc in choice.message.tool_calls
                        ]
            if raw_response.usage:
                usage = raw_response.usage

        elif hasattr(raw_response, "content") and hasattr(raw_response, "status_code"):
            # Handle ResponseEnvelope-like object
            response_content = getattr(raw_response, "content", None)
            if response_content is not None and isinstance(response_content, dict):
                # Explicitly cast to dict to help Mypy with type narrowing
                response_content = cast(dict[str, Any], response_content)
                choices = response_content.get("choices", [])
                if choices and isinstance(choices, list) and len(choices) > 0:
                    choice = choices[0]
                    if isinstance(choice, dict) and "message" in choice:
                        message = choice["message"]
                        if isinstance(message, dict):
                            message = cast(dict[str, Any], message)  # Explicit cast
                            if "content" in message:
                                content = message.get("content") or ""  # type: ignore[union-attr]
                            try:
                                tool_calls = message.get("tool_calls")
                                if tool_calls:
                                    metadata["tool_calls"] = tool_calls
                            except (AttributeError, TypeError) as e:
                                logger.debug(
                                    "Could not parse tool_calls: %s", e, exc_info=True
                                )
                            if (
                                content is not None
                                and isinstance(content, str)
                                and "Model 'bad' not found" in content
                            ):
                                metadata["http_status_override"] = 400
            usage = getattr(raw_response, "usage", None)  # type: ignore[attr-defined]

        elif isinstance(raw_response, dict):
            # Handle dictionary (for legacy support)
            metadata["model"] = raw_response.get("model", "unknown")
            metadata["id"] = raw_response.get("id", "")
            created_timestamp = raw_response.get("created", 0)
            if isinstance(created_timestamp, int | float):
                from datetime import datetime

                dt_object = datetime.utcfromtimestamp(created_timestamp)
                metadata["created"] = dt_object.isoformat(timespec="seconds")
            else:
                metadata["created"] = created_timestamp

            choices = raw_response.get("choices", [])
            if choices and isinstance(choices, list) and len(choices) > 0:
                choice = choices[0]
                if isinstance(choice, dict) and "message" in choice:
                    message = choice["message"]
                    if isinstance(message, dict):
                        if "content" in message:
                            content = message.get("content") or ""
                        try:
                            tool_calls = message.get("tool_calls")
                            if tool_calls:
                                metadata["tool_calls"] = tool_calls
                        except (AttributeError, TypeError) as e:
                            logger.debug(
                                "Could not parse tool_calls: %s", e, exc_info=True
                            )
            usage = raw_response.get("usage")

            # If content is still empty, prioritize tool_calls if present
            if not content:
                if metadata.get("tool_calls"):
                    content = json.dumps(metadata["tool_calls"])
                elif not choices:  # Original logic for non-chat dictionaries
                    content = json.dumps(raw_response)

        elif raw_response is None:
            content = ""

        elif isinstance(raw_response, str):
            content = raw_response
        else:
            raise ParsingError(f"Unsupported response type: {type(raw_response)}")

        return {"content": content, "usage": usage, "metadata": metadata}

    def extract_content(self, parsed_response: dict[str, Any]) -> str:
        """
        Extracts the main content string from a parsed response dictionary.
        """
        return str(parsed_response.get("content", ""))

    def extract_usage(self, parsed_response: dict[str, Any]) -> dict[str, Any] | None:
        """
        Extracts usage information from a parsed response dictionary.
        """
        return parsed_response.get("usage")

    def extract_metadata(
        self, parsed_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Extracts metadata from a parsed response dictionary.
        """
        return parsed_response.get("metadata")
