"""In-memory continuation lineage for the OpenAI Codex connector."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from src.connectors.openai_codex.contracts import CodexRequestContext
from src.connectors.openai_codex.interfaces import ICodexContinuationCoordinator
from src.connectors.openai_codex.utils import (
    fingerprint_component,
    fingerprint_input_items,
)

logger = logging.getLogger(__name__)

_CLINE_LIKE_ALIASES = {
    "kilocode",
    "kilo-code",
    "kilo_code",
    "kilocode.ai",
    "kilo",
    "kiloc",
    "roocode",
    "roo-code",
    "roo_code",
    "roo",
    "roo cline",
    "roo-cline",
    "roo_cline",
}
_DROID_USER_AGENT_PATTERNS = (
    "factory-cli",
    "factory_cli",
    "factorydroid",
)


@dataclass(slots=True)
class CodexContinuationSnapshot:
    response_id: str
    input_fingerprints: tuple[str, ...]
    instructions_fingerprint: str | None
    tools_fingerprint: str | None


@dataclass(slots=True)
class _ContinuationEntry:
    snapshot: CodexContinuationSnapshot
    expires_at: float


class InMemoryCodexContinuationCoordinator(ICodexContinuationCoordinator):
    """Ephemeral TTL/LRU-ish continuation store keyed by Codex request identity."""

    def __init__(
        self,
        *,
        ttl_seconds: float = 3600.0,
        max_entries: int = 1024,
    ) -> None:
        self._ttl_seconds = max(1.0, float(ttl_seconds))
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple[str, ...], _ContinuationEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def resolve_previous_response_id(
        self, context: CodexRequestContext
    ) -> str | None:
        key = self._build_key(context)
        now = time.monotonic()
        async with self._lock:
            self._purge_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return entry.snapshot.response_id

    async def record_response_id(
        self, context: CodexRequestContext, response_id: str
    ) -> None:
        normalized = response_id.strip()
        if not normalized:
            return
        key = self._build_key(context)
        now = time.monotonic()
        async with self._lock:
            self._purge_expired(now)
            existing = self._entries.get(key)
            prior_snapshot = existing.snapshot if existing is not None else None

            # L2: If we are recording just a response_id (e.g. from a partial stream
            # or terminal sync), we preserve prior fingerprints if available,
            # otherwise we start with empty fingerprints.
            self._entries[key] = _ContinuationEntry(
                snapshot=CodexContinuationSnapshot(
                    response_id=normalized,
                    input_fingerprints=(
                        prior_snapshot.input_fingerprints
                        if prior_snapshot is not None
                        else ()
                    ),
                    instructions_fingerprint=(
                        prior_snapshot.instructions_fingerprint
                        if prior_snapshot is not None
                        else None
                    ),
                    tools_fingerprint=(
                        prior_snapshot.tools_fingerprint
                        if prior_snapshot is not None
                        else None
                    ),
                ),
                expires_at=now + self._ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    async def get_snapshot(
        self, context: CodexRequestContext
    ) -> CodexContinuationSnapshot | None:
        key = self._build_key(context)
        now = time.monotonic()
        async with self._lock:
            self._purge_expired(now)
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry.snapshot

    async def record_turn(
        self,
        context: CodexRequestContext,
        *,
        response_id: str,
        payload_dict: dict[str, Any],
    ) -> None:
        normalized = response_id.strip()
        if not normalized:
            return
        key = self._build_key(context)
        now = time.monotonic()

        # M1: Uses shared fingerprinting utilities
        snapshot = CodexContinuationSnapshot(
            response_id=normalized,
            input_fingerprints=fingerprint_input_items(payload_dict.get("input")),
            instructions_fingerprint=fingerprint_component(
                payload_dict.get("instructions")
            ),
            tools_fingerprint=fingerprint_component(payload_dict.get("tools")),
        )
        async with self._lock:
            self._purge_expired(now)
            self._entries[key] = _ContinuationEntry(
                snapshot=snapshot,
                expires_at=now + self._ttl_seconds,
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    async def invalidate(
        self, context: CodexRequestContext, *, reason: str | None = None
    ) -> None:
        # N1: Improved logging for invalidation
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "Codex continuation lineage invalidated.",
                extra={
                    "session_id": context.session_id,
                    "reason": reason or "unspecified",
                },
            )
        key = self._build_key(context)
        async with self._lock:
            self._entries.pop(key, None)

    def build_key(self, context: CodexRequestContext) -> tuple[str, ...]:
        """Public stable key for continuation-scoped state (shared with WS v2 lineage)."""
        return self._build_key(context)

    def _build_key(self, context: CodexRequestContext) -> tuple[str, ...]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        backend = self._coerce_metadata_str(metadata.get("continuation_backend"))
        prompt_cache_key = self._coerce_metadata_str(
            metadata.get("continuation_prompt_cache_key")
        )
        account_id = self._coerce_metadata_str(metadata.get("continuation_account_id"))
        client_family = self._resolve_client_family(context)
        return (
            backend or "openai-codex",
            context.session_id,
            context.effective_model,
            account_id or "",
            prompt_cache_key or "",
            client_family,
        )

    def _purge_expired(self, now: float) -> None:
        expired_keys = [
            key for key, entry in self._entries.items() if entry.expires_at <= now
        ]
        for key in expired_keys:
            self._entries.pop(key, None)

    @staticmethod
    def _coerce_metadata_str(value: Any) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return None

    @classmethod
    def _resolve_client_family(cls, context: CodexRequestContext) -> str:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        headers = metadata.get("headers")
        user_agent: str | None = None
        if isinstance(headers, dict):
            for header_name in ("user-agent", "User-Agent"):
                header_value = headers.get(header_name)
                if isinstance(header_value, str) and header_value.strip():
                    user_agent = header_value
                    break

        candidates = (
            cls._coerce_metadata_str(metadata.get("agent")),
            cls._coerce_metadata_str(getattr(context.request, "agent", None)),
            cls._coerce_metadata_str(cls._get_extra_body_agent(context)),
            cls._coerce_metadata_str(user_agent),
        )
        for candidate in candidates:
            if candidate is None:
                continue
            family = cls._normalize_client_family(candidate)
            if family != "generic":
                return family
        return "generic"

    @staticmethod
    def _get_extra_body_agent(context: CodexRequestContext) -> Any:
        extra_body = getattr(context.request, "extra_body", None)
        if isinstance(extra_body, dict):
            return extra_body.get("agent")
        return None

    @classmethod
    def _normalize_client_family(cls, candidate: str) -> str:
        lowered = candidate.lower().strip()
        normalized = (
            lowered.split("/", 1)[0]
            .replace("-", "")
            .replace("_", "")
            .replace(".", "")
            .replace(" ", "")
        )
        if "opencode" in lowered:
            return "opencode"
        if lowered in _CLINE_LIKE_ALIASES or normalized in {
            "kilocode",
            "kiloc",
            "kilo",
            "roo",
            "roocode",
            "roocline",
            "cline",
            "clinelike",
        }:
            return "cline_like"
        if cls._is_droid_candidate(lowered):
            return "droid"
        return "generic"

    @staticmethod
    def _is_droid_candidate(lowered: str) -> bool:
        if any(pattern in lowered for pattern in _DROID_USER_AGENT_PATTERNS):
            return True
        tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}
        return "droid" in tokens
