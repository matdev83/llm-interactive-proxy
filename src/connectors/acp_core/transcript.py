from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from src.connectors.acp_core.tool_markdown import (
    format_transcript_assistant_tool_record,
    format_transcript_tool_message_record,
)
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
            ACPTranscriptSerializer._append_serialized_history_message(lines, msg)

        lines.append("------------------------")
        lines.append("")
        lines.append("[Current Request]")
        lines.append(last_user_msg)

        return "\n".join(lines)

    @staticmethod
    def serialize_tail(
        messages: Sequence[ChatMessage | dict[str, Any] | str | Any],
        start_index: int,
    ) -> str:
        """Serialize messages from ``start_index`` through the final user turn.

        Used when the ACP agent already saw messages ``[:start_index]`` and new
        messages were appended (e.g. non-ACP turns in between).
        """
        if start_index <= 0:
            return ACPTranscriptSerializer.serialize(messages)
        if not messages or start_index >= len(messages):
            return ""

        last_user_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if ACPTranscriptSerializer._get_role(messages[i]) == "user":
                last_user_idx = i
                break

        if last_user_idx == -1:
            return ""

        last_user_msg = ACPTranscriptSerializer._get_content(messages[last_user_idx])
        if last_user_idx < start_index:
            return last_user_msg

        history_msgs = list(messages[start_index:last_user_idx])
        if not history_msgs:
            return last_user_msg

        lines = [
            "[System Note: Additional conversation occurred since your last response. "
            "Here is the new context:]",
            "",
            "--- New Messages ---",
        ]

        for msg in history_msgs:
            ACPTranscriptSerializer._append_serialized_history_message(lines, msg)

        lines.append("------------------------")
        lines.append("")
        lines.append("[Current Request]")
        lines.append(last_user_msg)

        return "\n".join(lines)

    @staticmethod
    def _append_serialized_history_message(lines: list[str], msg: Any) -> None:
        role = ACPTranscriptSerializer._get_role(msg)
        content = ACPTranscriptSerializer._get_content(msg)

        if role == "system":
            lines.append(f"**System:** {content}")
        elif role == "user":
            lines.append(f"**User:** {content}")
        elif role == "assistant":
            lines.append(f"**Assistant:** {content}")
            tool_calls = ACPTranscriptSerializer._get_tool_calls(msg)
            for tc in tool_calls:
                fn_block = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn_block, dict):
                    name = fn_block.get("name") or "unknown"
                    args: Any = fn_block.get("arguments")
                else:
                    name = (
                        tc.get("name", "unknown") if isinstance(tc, dict) else "unknown"
                    )
                    args = tc.get("arguments") if isinstance(tc, dict) else None
                block = format_transcript_assistant_tool_record(
                    str(name) if name is not None else "unknown", args
                ).rstrip("\n")
                if block:
                    lines.append(block)
        elif role == "tool":
            tid, tname = ACPTranscriptSerializer._tool_message_ids(msg)
            raw_payload = ACPTranscriptSerializer._get_tool_message_payload(msg)
            block = format_transcript_tool_message_record(
                tool_call_id=tid, name=tname, content=raw_payload
            ).rstrip("\n")
            if block:
                lines.append(block)
        else:
            lines.append(f"**{role.capitalize()}:** {content}")

    @staticmethod
    def _tool_message_ids(msg: Any) -> tuple[str | None, str | None]:
        if isinstance(msg, ChatMessage):
            return (msg.tool_call_id, msg.name)
        if isinstance(msg, dict):
            tid_raw = msg.get("tool_call_id")
            name_raw = msg.get("name")
            return (
                None if tid_raw is None else str(tid_raw),
                None if name_raw is None else str(name_raw),
            )
        tid = getattr(msg, "tool_call_id", None)
        tname = getattr(msg, "name", None)
        return (
            None if tid is None else str(tid),
            None if tname is None else str(tname),
        )

    @staticmethod
    def _get_tool_message_payload(msg: Any) -> Any:
        """Raw ``content`` for tool messages (may be structured, not flattened)."""
        if isinstance(msg, ChatMessage):
            return msg.content
        if isinstance(msg, dict):
            c = msg.get("content")
            if c in (None, "") and "parts" in msg:
                return msg.get("parts")
            return c
        return getattr(msg, "content", "")

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
