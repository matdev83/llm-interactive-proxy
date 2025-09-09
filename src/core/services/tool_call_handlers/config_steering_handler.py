"""
Configurable Steering Tool Call Handler.

This handler reads user-defined steering rules from configuration and applies
them to tool-call events. It can steer based on tool name and/or trigger
phrases found within the tool name or arguments.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


@dataclass
class _CompiledRule:
    name: str
    enabled: bool
    message: str
    calls_per_window: int
    window_seconds: int
    priority: int
    trigger_tool_names: list[str]
    trigger_phrases: list[str]


class ConfigSteeringHandler(IToolCallHandler):
    """Generic, config-driven steering handler.

    Matching logic:
    - Exact match on tool name (case-sensitive) if provided
    - OR substring (case-insensitive) of any trigger phrase within the tool
      name or serialized arguments
    Rate limiting is tracked per (session_id, rule.name).
    """

    def __init__(self, rules: list[dict[str, Any]] | None = None) -> None:
        compiled: list[_CompiledRule] = []
        for idx, raw in enumerate(rules or []):
            try:
                name = str(raw.get("name") or f"rule_{idx}")
                enabled = bool(raw.get("enabled", True))
                msg = str(raw.get("message") or "")
                if not msg:
                    # Skip invalid rule: message required
                    continue
                rl = raw.get("rate_limit") or {}
                calls_per_window = int(rl.get("calls_per_window", 1))
                window_seconds = int(rl.get("window_seconds", 60))
                prio = int(raw.get("priority", 50))
                triggers = raw.get("triggers") or {}
                tool_names = triggers.get("tool_names") or []
                phrases = triggers.get("phrases") or []
                compiled.append(
                    _CompiledRule(
                        name=name,
                        enabled=enabled,
                        message=msg,
                        calls_per_window=calls_per_window,
                        window_seconds=window_seconds,
                        priority=prio,
                        trigger_tool_names=[str(t) for t in tool_names if t],
                        trigger_phrases=[str(p) for p in phrases if p],
                    )
                )
            except Exception as e:
                logger.warning(
                    "Invalid steering rule at index %s: %s", idx, e, exc_info=True
                )

        # Highest priority first, keep stable order otherwise
        self._rules: list[_CompiledRule] = sorted(
            compiled, key=lambda r: r.priority, reverse=True
        )
        self._last_hits: dict[tuple[str, str], list[datetime]] = {}

    @property
    def name(self) -> str:
        return "config_steering_handler"

    @property
    def priority(self) -> int:
        # Lower than security/legacy to preserve backward compatibility
        return 90

    async def can_handle(self, context: ToolCallContext) -> bool:
        rule = self._match_rule(context)
        if not rule:
            return False
        return self._within_rate_limit(rule, context.session_id)

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        rule = self._match_rule(context)
        if not rule:
            return ToolCallReactionResult(should_swallow=False)

        # Record hit for rate limiting
        self._record_hit(rule, context.session_id)

        logger.info(
            "Steering via rule '%s' for tool '%s' in session %s",
            rule.name,
            context.tool_name,
            context.session_id,
        )

        # Swallow and return configured message
        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response=rule.message,
            metadata={
                "handler": self.name,
                "rule": rule.name,
                "tool_name": context.tool_name,
                "source": "config_steering",
            },
        )

    def _match_rule(self, context: ToolCallContext) -> _CompiledRule | None:
        tool_name = context.tool_name or ""
        # Serialize args safely for phrase matching
        try:
            args_str = json.dumps(context.tool_arguments, ensure_ascii=False)
        except Exception:
            args_str = str(context.tool_arguments)
        haystack = f"{tool_name}\n{args_str}".lower()

        for rule in self._rules:
            if not rule.enabled:
                continue
            # Exact tool name match
            if rule.trigger_tool_names and tool_name in rule.trigger_tool_names:
                return rule
            # Phrase match (case-insensitive)
            if rule.trigger_phrases:
                for phrase in rule.trigger_phrases:
                    if phrase and phrase.lower() in haystack:
                        return rule
        return None

    def _within_rate_limit(self, rule: _CompiledRule, session_id: str) -> bool:
        key = (session_id, rule.name)
        hits = self._last_hits.get(key, [])
        now = datetime.now()
        window_start = now - timedelta(seconds=rule.window_seconds)
        hits = [h for h in hits if h >= window_start]
        self._last_hits[key] = hits
        return len(hits) < rule.calls_per_window

    def _record_hit(self, rule: _CompiledRule, session_id: str) -> None:
        key = (session_id, rule.name)
        hits = self._last_hits.get(key, [])
        hits.append(datetime.now())
        # Keep small history per key
        if len(hits) > 20:
            hits = hits[-20:]
        self._last_hits[key] = hits
