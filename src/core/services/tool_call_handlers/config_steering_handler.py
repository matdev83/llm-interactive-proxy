"""
Configurable Steering Tool Call Handler.

This handler reads user-defined steering rules from configuration and applies
them to tool-call events. It can steer based on tool name and/or trigger
phrases found within the tool name or arguments.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)
_NON_ALNUM_PATTERN = re.compile(r"[\W_]+")


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
    _compiled_phrases: list[tuple[str, set[str], set[str]]] = field(
        init=False, default_factory=list
    )

    def __post_init__(self):
        """Pre-compile phrase triggers for faster matching."""
        for phrase in self.trigger_phrases:
            if not phrase:
                continue
            phrase_lower = phrase.lower()
            segments = {phrase_lower}
            tokens = phrase_lower.split()
            if tokens:
                non_flag_tokens = [
                    token for token in tokens if not token.startswith("-")
                ]
                if non_flag_tokens:
                    segments.add(" ".join(non_flag_tokens))
                    if len(non_flag_tokens) >= 2:
                        segments.add(" ".join(non_flag_tokens[:2]))

            sanitized_segments = {
                _NON_ALNUM_PATTERN.sub("", segment) for segment in segments if segment
            }
            sanitized_segments.add(_NON_ALNUM_PATTERN.sub("", phrase_lower))

            self._compiled_phrases.append((phrase_lower, segments, sanitized_segments))


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

        # Build tool name index for faster lookups
        self._tool_name_index: dict[str, list[_CompiledRule]] = {}
        self._phrase_only_rules: list[_CompiledRule] = []
        for rule in self._rules:
            if not rule.enabled:
                continue

            if rule.trigger_tool_names:
                for tool_name in rule.trigger_tool_names:
                    if tool_name not in self._tool_name_index:
                        self._tool_name_index[tool_name] = []
                    self._tool_name_index[tool_name].append(rule)
            elif rule.trigger_phrases:
                self._phrase_only_rules.append(rule)

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
        await self._record_hit(rule, context.session_id)

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

        # Get potential candidates from index and phrase-only rules
        # This is much faster than iterating all rules every time.
        candidate_rules = self._tool_name_index.get(tool_name, [])

        # Combine and sort by priority to respect rule precedence
        # The lists are already sorted by priority, so a merge would be ideal,
        # but for simplicity, we can just combine and re-sort.
        # Given the small number of candidates, this is fast enough.
        all_candidates = sorted(
            candidate_rules + self._phrase_only_rules,
            key=lambda r: r.priority,
            reverse=True,
        )

        if not all_candidates:
            return None

        # Serialize args safely for phrase matching (only once)
        try:
            args_str = json.dumps(context.tool_arguments, ensure_ascii=False)
        except Exception:
            args_str = str(context.tool_arguments)
        haystack = f"{tool_name}\n{args_str}"
        haystack_lower = haystack.lower()
        compact_haystack = _NON_ALNUM_PATTERN.sub("", haystack_lower)

        for rule in all_candidates:
            # Rule enabled status is already checked when building index
            tool_match = tool_name in rule.trigger_tool_names

            phrase_match = False
            if rule.trigger_phrases:
                for _, segments, sanitized_segments in rule._compiled_phrases:
                    if any(s and s in haystack_lower for s in segments):
                        phrase_match = True
                        break
                    if any(s and s in compact_haystack for s in sanitized_segments):
                        phrase_match = True
                        break

            if tool_match or phrase_match:
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

    async def _record_hit(self, rule: _CompiledRule, session_id: str) -> None:
        key = (session_id, rule.name)
        hits = self._last_hits.get(key, [])
        hits.append(datetime.now())
        # Keep small history per key
        if len(hits) > 20:
            hits = hits[-20:]
        self._last_hits[key] = hits
