from __future__ import annotations

from src.core.interfaces.command_detector_interface import ICommandDetector
from src.core.services.command_service import get_command_pattern


class CommandDetector(ICommandDetector):
    """Default detector using shared get_command_pattern."""

    def detect(self, content: str) -> dict[str, object] | None:
        if not content:
            return None
        pattern = get_command_pattern("!/")
        m = pattern.search(content)
        if not m:
            return None
        cmd_name = (m.group("cmd") or "").strip()
        args_str = (m.group("args") or "").strip() or None
        return {
            "cmd_name": cmd_name,
            "args_str": args_str,
            "match_start": m.start(),
            "match_end": m.end(),
        }
