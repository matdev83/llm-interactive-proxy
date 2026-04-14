from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from src.core.domain.chat import ChatMessage


class ACPTranscriptSerializer:
    """Serializes conversation history into a Markdown transcript for ACP sessions."""

    @staticmethod
    def serialize(messages: Sequence[ChatMessage | dict[str, Any] | str | Any]) -> str:
        """Convert messages into a Markdown preamble and the final user prompt.

        Args:
            messages: The conversation history.

        Returns:
            A single string containing the serialized transcript and the final prompt.
        """
        if not messages:
            return ""

        # Extract the last user message to be the actual prompt
        last_user_msg = ""
        history_msgs = []

        # Find the last user message
        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            role = ACPTranscriptSerializer._get_role(msg)
            if role == "user":
                last_user_idx = i
                break

        if last_user_idx != -1:
            last_user_msg = ACPTranscriptSerializer._get_content(
                messages[last_user_idx]
            )
            history_msgs = list(messages[:last_user_idx])
        else:
            history_msgs = list(messages)

        if not history_msgs:
            return last_user_msg

        lines = [
            "[System Note: The user is continuing a previous session. Here is the context of what happened so far:]",
            "",
            "--- Previous Context ---",
        ]

        for msg in history_msgs:
            role = ACPTranscriptSerializer._get_role(msg)
            content = ACPTranscriptSerializer._get_content(msg)

            if role == "system":
                lines.append(f"**System:** {content}")
            elif role == "user":
                lines.append(f"**User:** {content}")
            elif role == "assistant":
                lines.append(f"**Assistant:** {content}")

                # Handle tool calls if present
                tool_calls = ACPTranscriptSerializer._get_tool_calls(msg)
                for tc in tool_calls:
                    func_name = tc.get("function", {}).get("name", "unknown")
                    func_args = tc.get("function", {}).get("arguments", "{}")
                    lines.append(f"*Tool Call (`{func_name}`)*: `{func_args}`")
            elif role == "tool":
                lines.append(f"*Tool Result*: `{content}`")
            else:
                lines.append(f"**{role.capitalize()}:** {content}")

        lines.append("------------------------")
        lines.append("")
        lines.append("[Current Request]")
        lines.append(last_user_msg)

        return "\n".join(lines)

    @staticmethod
    def _get_role(msg: Any) -> str:
        if isinstance(msg, ChatMessage):
            return msg.role
        if isinstance(msg, dict):
            return str(msg.get("role", ""))
        if isinstance(msg, str):
            return "user"
        return str(getattr(msg, "role", ""))

    @staticmethod
    def _get_content(msg: Any) -> str:
        content: Any = ""
        if isinstance(msg, ChatMessage):
            content = msg.content
        elif isinstance(msg, dict):
            content = msg.get("content")
            if content in (None, "") and "parts" in msg:
                content = msg.get("parts")
        elif isinstance(msg, str):
            content = msg
        else:
            content = getattr(msg, "content", "")

        return ACPTranscriptSerializer._stringify_content(content)

    @staticmethod
    def _get_tool_calls(msg: Any) -> list[dict[str, Any]]:
        if isinstance(msg, ChatMessage):
            # ChatMessage might not have tool_calls directly typed, but it could be in extra fields
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # Convert to dict if needed
                out: list[dict[str, Any]] = []
                for tc in getattr(msg, "tool_calls", []):
                    if isinstance(tc, dict):
                        out.append(tc)
                    else:
                        dumped: dict[str, Any] = cast(
                            dict[str, Any], getattr(tc, "model_dump", dict)()
                        )
                        out.append(dumped)
                return out
            return []
        if isinstance(msg, dict):
            raw = msg.get("tool_calls", [])
            if isinstance(raw, list):
                return cast(list[dict[str, Any]], raw)
            return []
        raw_attr = getattr(msg, "tool_calls", [])
        if isinstance(raw_attr, list):
            return cast(list[dict[str, Any]], raw_attr)
        return []

    @staticmethod
    def _stringify_content(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, Sequence) and not isinstance(
            content, str | bytes | bytearray
        ):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    nested = item.get("content")
                    if isinstance(text, str):
                        parts.append(text)
                    elif isinstance(nested, str):
                        parts.append(nested)
                else:
                    item_text = getattr(item, "text", None)
                    if isinstance(item_text, str):
                        parts.append(item_text)
            return " ".join(part for part in parts if part)
        return str(content)
