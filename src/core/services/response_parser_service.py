import json
import logging
from typing import Any, cast

from src.core.common.exceptions import ParsingError
from src.core.domain.chat import ChatResponse
from src.core.interfaces.response_parser_interface import IResponseParser

logger = logging.getLogger(__name__)


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
            from datetime import datetime, timezone

            dt_object = datetime.fromtimestamp(raw_response.created, tz=timezone.utc)
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
                # Check for Responses API format (response.choices) first
                # If it's a Responses API response, preserve the full structure in metadata
                # so that the content converter can reconstruct it later
                if "response" in response_content and isinstance(
                    response_content.get("response"), dict
                ):
                    # This is a Responses API response - preserve the full structure
                    metadata["original_responses_api_response"] = response_content
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "ResponseParser preserved Responses API response in metadata - response_id=%s",
                            response_content.get("id", "unknown"),
                        )
                    # Extract content from response.choices[0].message.content for compatibility
                    response_wrapper = response_content.get("response", {})
                    choices = response_wrapper.get("choices", [])
                else:
                    # Fall back to Chat Completions format (choices at top level)
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
                                if logger.isEnabledFor(logging.DEBUG):
                                    logger.debug(
                                        "Could not parse tool_calls: %s",
                                        e,
                                        exc_info=True,
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
                from datetime import datetime, timezone

                dt_object = datetime.fromtimestamp(created_timestamp, tz=timezone.utc)
                metadata["created"] = dt_object.isoformat(timespec="seconds")
            else:
                metadata["created"] = created_timestamp

            choices = raw_response.get("choices", [])
            # Log when we see empty choices - this could indicate unusual backend behavior
            if (
                not choices
                and "choices" in raw_response
                and logger.isEnabledFor(logging.DEBUG)
            ):
                logger.debug(
                    "Response has empty choices array - model=%s id=%s",
                    raw_response.get("model", "unknown"),
                    raw_response.get("id", "unknown"),
                )
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
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Could not parse tool_calls: %s", e, exc_info=True
                                )
            usage = raw_response.get("usage")

            # If content is still empty and choices key is completely missing (not just empty),
            # serialize the entire response. This handles edge cases like non-chat completion
            # responses (e.g., embeddings API).
            # Note: Empty choices array (choices: []) is a valid response indicating no output
            # was generated - we should NOT serialize the entire response in that case.
            if not content and "choices" not in raw_response:
                content = json.dumps(raw_response)

        elif raw_response is None:
            content = ""
        elif isinstance(raw_response, str):
            # Handle string responses (e.g., JSON strings or plain text)
            content = raw_response
            # Don't add default metadata for plain strings
        else:
            # Unsupported type - raise ParsingError
            raise ParsingError(
                f"Unsupported response type: {type(raw_response).__name__}",
                details={"type": type(raw_response).__name__},
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("ResponseParser metadata: %s", metadata)

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
        usage = parsed_response.get("usage")
        from src.core.domain.usage_summary import UsageSummary

        if isinstance(usage, UsageSummary):
            return usage.to_legacy_dict()
        if isinstance(usage, dict):
            return usage
        return None

    def extract_metadata(
        self, parsed_response: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Extracts metadata from a parsed response dictionary.
        """
        return parsed_response.get("metadata")
