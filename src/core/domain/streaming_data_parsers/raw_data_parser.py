from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.streaming_content import StreamingContent

logger = logging.getLogger(__name__)


class IRawDataParser(ABC):
    """Interface for parsing raw streaming data into StreamingContent."""

    @abstractmethod
    def parse(self, data: Any) -> StreamingContent:
        """Parse raw data into a StreamingContent object."""


class BytesParser(IRawDataParser):
    """Parses bytes data into StreamingContent."""

    def parse(self, data: bytes) -> StreamingContent:
        try:
            text = data.decode("utf-8").strip()

            if text == "data: [DONE]":
                return StreamingContent(is_done=True, raw_data=data)

            if text.startswith("data: "):
                text = text[6:]

                if text == "[DONE]":
                    return StreamingContent(is_done=True, raw_data=data)

                try:
                    json_data = json.loads(text)
                    # Recursively call from_raw to handle nested JSON structures
                    return StreamingContent.from_raw(json_data)
                except json.JSONDecodeError:
                    return StreamingContent(content=text, raw_data=data)

            try:
                json_data = json.loads(text)
                return StreamingContent.from_raw(json_data)
            except json.JSONDecodeError:
                return StreamingContent(content=text, raw_data=data)

        except Exception as e:
            logger.warning(f"Error parsing bytes data: {e}")
            return StreamingContent(
                content="", metadata={"parse_error": True}, raw_data=data
            )


class DictParser(IRawDataParser):
    """Parses dictionary data (OpenAI-compatible) into StreamingContent."""

    def parse(self, data: dict[str, Any]) -> StreamingContent:
        content = ""
        metadata = {
            "id": data.get("id", ""),
            "model": data.get("model", "unknown"),
            "created": data.get("created", 0),
        }

        choices = data.get("choices", [])
        if choices and isinstance(choices, list) and len(choices) > 0:
            choice = choices[0]
            if isinstance(choice, dict):
                if "delta" in choice:
                    delta = choice["delta"]
                    if isinstance(delta, dict) and "content" in delta:
                        content = delta.get("content") or ""
                elif "message" in choice:
                    message = choice["message"]
                    if isinstance(message, dict) and "content" in message:
                        content = message.get("content") or ""

        usage = data.get("usage")

        return StreamingContent(
            content=content, metadata=metadata, usage=usage, raw_data=data
        )


class StringParser(IRawDataParser):
    """Parses string data into StreamingContent."""

    def parse(self, data: str) -> StreamingContent:
        if data.strip().startswith(("{", "[")):
            try:
                json_data = json.loads(data)
                return StreamingContent.from_raw(json_data)
            except json.JSONDecodeError:
                pass

        return StreamingContent(content=data, raw_data=data)


class StreamingContentParser(IRawDataParser):
    """Handles already processed StreamingContent objects."""

    def parse(self, data: StreamingContent) -> StreamingContent:
        return data
