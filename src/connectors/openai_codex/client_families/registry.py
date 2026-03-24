"""Registry/orchestrator for client-family adapters."""

from __future__ import annotations

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CompatibilityState,
    ProviderStreamChunk,
)


class ClientFamilyRegistry:
    """Executes compatibility adapters in deterministic order."""

    def __init__(self, adapters: list[IClientFamilyAdapter] | None = None) -> None:
        self._adapters: list[IClientFamilyAdapter] = list(adapters or [])

    def register(self, adapter: IClientFamilyAdapter) -> None:
        self._adapters.append(adapter)

    async def detect_all(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> None:
        for adapter in self._adapters:
            await adapter.detect(context, state)

    async def apply_all(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> FamilyApplyResult:
        merged = FamilyApplyResult()
        for adapter in self._adapters:
            result = await adapter.apply(context, state)
            merged.codex_tools.extend(result.codex_tools)
            merged.proxy_tools.extend(result.proxy_tools)
            merged.mcp_tools.extend(result.mcp_tools)
            merged.tool_results.extend(result.tool_results)
        return merged

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        result = chunk
        for adapter in self._adapters:
            result = await adapter.translate_stream_chunk(result, state)
        return result

    async def cleanup_state(self, state: CompatibilityState) -> None:
        for adapter in self._adapters:
            await adapter.cleanup_state(state)

    def adapt_payload_dict(
        self,
        payload_dict: dict[str, object],
        context: CodexRequestContext,
        *,
        resolved_instructions: str | None = None,
    ) -> dict[str, object]:
        result = dict(payload_dict)
        for adapter in self._adapters:
            result = adapter.adapt_payload_dict(
                result,
                context,
                resolved_instructions=resolved_instructions,
            )
        return result

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        incompatible: list[str] = []
        for adapter in self._adapters:
            incompatible.extend(
                adapter.detect_incompatible_tool_calls(tool_calls, context)
            )
        # Preserve order while deduplicating
        return list(dict.fromkeys(name for name in incompatible if name))

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        result = dict(payload_dict)
        for adapter in self._adapters:
            result = adapter.append_incompatible_tool_steering(
                result,
                incompatible_tool_names,
                context,
            )
        return result
