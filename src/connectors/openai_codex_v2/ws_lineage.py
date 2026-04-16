"""Websocket v2 continuation lineage aligned with vendored Codex client rules."""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, cast

from src.connectors.openai_codex.contracts import CodexRequestContext
from src.connectors.openai_codex.interfaces import ICodexContinuationCoordinator

logger = logging.getLogger(__name__)

_WS_SKIP_COMPARE = frozenset({"input", "stream", "background", "previous_response_id"})


def codex_request_without_input_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip transport-only and variable fields for non-input equality checks."""
    return {k: v for k, v in payload.items() if k not in _WS_SKIP_COMPARE}


class CodexWebsocketV2Lineage:
    """Tracks last ``response.create`` envelope and assistant output items per continuation key."""

    def __init__(self, coordinator: ICodexContinuationCoordinator) -> None:
        self._coordinator = coordinator
        self._lock = asyncio.Lock()
        self._entries: dict[tuple[str, ...], dict[str, Any]] = {}

    def _key(self, context: CodexRequestContext) -> tuple[str, ...]:
        build = getattr(self._coordinator, "build_key", None)
        if not callable(build):
            raise TypeError("continuation coordinator must expose build_key()")
        raw = build(context)
        if not isinstance(raw, tuple):
            raise TypeError("build_key() must return a tuple key")
        return cast(tuple[str, ...], raw)

    async def invalidate(self, context: CodexRequestContext, *, reason: str) -> None:
        async with self._lock:
            self._entries.pop(self._key(context), None)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Dropped WS v2 lineage (%s)", reason)

    async def try_prepare_websocket_continuation(
        self,
        *,
        continuation_context: CodexRequestContext,
        payload_dict: dict[str, Any],
        full_payload_dict: dict[str, Any],
    ) -> tuple[bool, dict[str, Any], str, bool]:
        """Return ``(handled, payload_dict, continuation_reason, proxy_managed)``.

        ``handled`` is False when the caller should run the legacy Codex websocket
        continuation branch (first turn or no stored lineage yet).
        """
        if "previous_response_id" in payload_dict:
            return True, payload_dict, "client_previous_response_id_present", False

        previous_response_id = await self._coordinator.resolve_previous_response_id(
            continuation_context
        )
        if not previous_response_id:
            return True, payload_dict, "no_previous_response_id_available", False

        key = self._key(continuation_context)
        async with self._lock:
            entry = self._entries.get(key)

        if entry is None:
            return False, payload_dict, "", False

        last_sent = entry.get("last_sent")
        items_added = entry.get("items_added") or []
        if not isinstance(last_sent, dict):
            return False, payload_dict, "", False

        prev_wo = codex_request_without_input_fields(last_sent)
        cur_wo = codex_request_without_input_fields(payload_dict)
        if prev_wo != cur_wo:
            await self._coordinator.invalidate(
                continuation_context, reason="ws_v2_non_input_drift"
            )
            await self.invalidate(continuation_context, reason="ws_v2_non_input_drift")
            payload_dict.pop("previous_response_id", None)
            payload_dict["input"] = copy.deepcopy(full_payload_dict.get("input"))
            return True, payload_dict, "ws_v2_full_bootstrap_after_drift", False

        last_input = last_sent.get("input")
        current_input = payload_dict.get("input")
        if not isinstance(last_input, list) or not isinstance(current_input, list):
            await self._coordinator.invalidate(
                continuation_context, reason="ws_v2_input_shape"
            )
            await self.invalidate(continuation_context, reason="ws_v2_input_shape")
            payload_dict.pop("previous_response_id", None)
            payload_dict["input"] = copy.deepcopy(full_payload_dict.get("input"))
            return True, payload_dict, "ws_v2_full_bootstrap_bad_input", False

        baseline: list[Any] = list(last_input)
        baseline.extend(items_added)
        blen = len(baseline)
        if len(current_input) < blen or current_input[:blen] != baseline:
            await self._coordinator.invalidate(
                continuation_context, reason="ws_v2_prefix_mismatch"
            )
            await self.invalidate(continuation_context, reason="ws_v2_prefix_mismatch")
            payload_dict.pop("previous_response_id", None)
            payload_dict["input"] = copy.deepcopy(full_payload_dict.get("input"))
            return True, payload_dict, "ws_v2_full_bootstrap_prefix", False

        # Vendored Codex v2 allows an empty incremental suffix (``allow_empty_delta``).
        delta_slice: list[Any] = (
            [] if len(current_input) == blen else list(current_input[blen:])
        )

        payload_dict["previous_response_id"] = previous_response_id
        payload_dict["input"] = delta_slice
        reason = (
            "ws_v2_delta_applied" if delta_slice else "ws_v2_delta_empty_suffix_allowed"
        )
        return True, payload_dict, reason, True

    async def record_completed_websocket_turn(
        self,
        context: CodexRequestContext,
        *,
        sent_payload: dict[str, Any],
        response_id: str,
        items_added: list[Any],
    ) -> None:
        normalized = response_id.strip()
        if not normalized:
            return
        key = self._key(context)
        async with self._lock:
            self._entries[key] = {
                "last_sent": copy.deepcopy(sent_payload),
                "items_added": copy.deepcopy(items_added),
                "response_id": normalized,
            }
