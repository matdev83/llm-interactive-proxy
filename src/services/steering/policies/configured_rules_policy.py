"""Configurable steering rules policy."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import ToolCallContext

from ..interfaces import ISteeringPolicy
from ..models import SteeringResult, SteeringRule
from ..session_state_store import SessionStateStore


logger = logging.getLogger(__name__)
_NON_ALNUM_PATTERN = re.compile(r"[\W_]+")


@dataclass
class _CompiledRule:
    """Compiled steering rule for faster matching."""

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


class ConfiguredRulesPolicy(ISteeringPolicy):
    """Policy that applies user-defined steering rules from configuration.

    Supports:
    - Tool name matching (exact, case-sensitive)
    - Phrase matching (substring, case-insensitive) in tool name/arguments
    - Rate limiting per (session, rule)
    - Priority-based rule evaluation
    """

    def __init__(
        self,
        session_store: SessionStateStore,
        rules: list[SteeringRule] | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the policy.

        Args:
            session_store: Shared session state store
            rules: List of rule definitions from config
            enabled: Whether the policy is enabled
        """
        self._session_store = session_store
        self._enabled = enabled
        self._rules = self._compile_rules(rules or [])

        # self._last_hits removed in favor of SessionStateStore

        # Build tool name index for fast lookups
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
        return "configured_rules"

    @property
    def priority(self) -> int:
        # Lower than specific policies (inline python, pytest) to preserve precedence
        return 90

    async def evaluate(
        self, context: ToolCallContext, command: str, dry_run: bool = False
    ) -> SteeringResult | None:
        """Evaluate if any configured rule matches."""
        if not self._enabled:
            return None

        rule = self._match_rule(context, command)
        if not rule:
            return None

        # Check rate limit
        if not await self._within_rate_limit(rule, context.session_id):
            return None

        if not dry_run:
            # Record hit
            await self._record_hit(rule, context.session_id)

        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Steering via rule '%s' for tool '%s' in session %s",
                rule.name,
                context.tool_name,
                context.session_id,
            )

        return SteeringResult(
            message=rule.message,
            should_block=True,
            policy_name=self.name,
            severity="warning",
            metadata={
                "rule_name": rule.name,
                "tool_name": context.tool_name,
                "source": "config_steering",
            },
        )

    def _compile_rules(self, rules: list[SteeringRule]) -> list[_CompiledRule]:
        """Compile raw rules into optimized internal format."""
        compiled: list[_CompiledRule] = []

        for rule in rules:
            try:
                if not rule.message:
                    continue  # Skip invalid rule

                compiled.append(
                    _CompiledRule(
                        name=rule.name,
                        enabled=rule.enabled,
                        message=rule.message,
                        calls_per_window=rule.rate_limit.calls_per_window,
                        window_seconds=rule.rate_limit.window_seconds,
                        priority=rule.priority,
                        trigger_tool_names=[
                            str(t) for t in rule.triggers.tool_names if t
                        ],
                        trigger_phrases=[str(p) for p in rule.triggers.phrases if p],
                    )
                )
            except Exception as e:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning("Error compiling steering rule %s: %s", rule.name, e)

        # Sort by priority (highest first)
        return sorted(compiled, key=lambda r: r.priority, reverse=True)


    def _match_rule(
        self, context: ToolCallContext, command: str
    ) -> _CompiledRule | None:
        """Find first matching rule based on tool name and/or phrases."""
        tool_name = context.tool_name or ""

        # Get candidates from index
        candidate_rules = self._tool_name_index.get(tool_name, [])

        # Combine with phrase-only rules and sort by priority
        all_candidates = sorted(
            candidate_rules + self._phrase_only_rules,
            key=lambda r: r.priority,
            reverse=True,
        )

        if not all_candidates:
            return None

        # Serialize args for phrase matching
        try:
            args_str = json.dumps(context.tool_arguments, ensure_ascii=False)
        except Exception:
            args_str = str(context.tool_arguments)

        haystack = f"{tool_name}\n{args_str}"
        haystack_lower = haystack.lower()
        compact_haystack = _NON_ALNUM_PATTERN.sub("", haystack_lower)

        for rule in all_candidates:
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

    async def _within_rate_limit(self, rule: _CompiledRule, session_id: str) -> bool:
        """Check if rule is within rate limit for this session."""
        key = f"rule_hits:{rule.name}"
        hits: list[float] = await self._session_store.get(session_id, key, default=[])

        now = datetime.now(timezone.utc).timestamp()
        window_start = now - rule.window_seconds

        # Filter hits in window (non-mutating)
        valid_hits = [h for h in hits if h >= window_start]

        return len(valid_hits) < rule.calls_per_window

    async def _record_hit(self, rule: _CompiledRule, session_id: str) -> None:
        """Record a hit for rate limiting."""
        key = f"rule_hits:{rule.name}"

        def update_hits(hits: list[float] | None) -> list[float]:
            if hits is None:
                hits = []

            now = datetime.now(timezone.utc).timestamp()
            window_start = now - rule.window_seconds

            # Filter valid hits and append new one
            valid_hits = [h for h in hits if h >= window_start]
            valid_hits.append(now)

            # Limit stored history size
            if len(valid_hits) > max(20, rule.calls_per_window * 2):
                valid_hits = valid_hits[-max(20, rule.calls_per_window * 2) :]

            return valid_hits

        await self._session_store.update(session_id, key, update_hits, default=[])


__all__ = ["ConfiguredRulesPolicy"]
