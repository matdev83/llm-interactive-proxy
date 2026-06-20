from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .auth_scope_resolver_service import DefaultAuthScopeResolver
    from .b2bua_bleg_allocator_service import B2buaBlegAllocator, BlegAllocation
    from .b2bua_mapping_store_service import (
        B2buaAttemptRecord,
        B2buaContinuityResolution,
        InMemoryB2buaMappingStore,
        PersistentB2buaMappingStore,
    )
    from .b2bua_session_id_factory import B2BUASessionIdFactory
    from .b2bua_session_resolver_service import B2BUASessionResolver
    from .client_session_id_extractor_service import DefaultClientSessionIdExtractor
    from .json_repair_service import JsonRepairService
    from .structured_output_middleware import StructuredOutputMiddleware

__all__ = [
    "DefaultAuthScopeResolver",
    "B2buaBlegAllocator",
    "BlegAllocation",
    "B2buaAttemptRecord",
    "B2buaContinuityResolution",
    "InMemoryB2buaMappingStore",
    "PersistentB2buaMappingStore",
    "B2BUASessionIdFactory",
    "B2BUASessionResolver",
    "DefaultClientSessionIdExtractor",
    "JsonRepairService",
    "StructuredOutputMiddleware",
]


def __getattr__(name: str) -> object:
    if name == "DefaultAuthScopeResolver":
        from .auth_scope_resolver_service import DefaultAuthScopeResolver

        return DefaultAuthScopeResolver
    if name in {"B2buaBlegAllocator", "BlegAllocation"}:
        from .b2bua_bleg_allocator_service import B2buaBlegAllocator, BlegAllocation

        return {
            "B2buaBlegAllocator": B2buaBlegAllocator,
            "BlegAllocation": BlegAllocation,
        }[name]
    if name in {
        "B2buaAttemptRecord",
        "B2buaContinuityResolution",
        "InMemoryB2buaMappingStore",
        "PersistentB2buaMappingStore",
    }:
        from .b2bua_mapping_store_service import (
            B2buaAttemptRecord,
            B2buaContinuityResolution,
            InMemoryB2buaMappingStore,
            PersistentB2buaMappingStore,
        )

        return {
            "B2buaAttemptRecord": B2buaAttemptRecord,
            "B2buaContinuityResolution": B2buaContinuityResolution,
            "InMemoryB2buaMappingStore": InMemoryB2buaMappingStore,
            "PersistentB2buaMappingStore": PersistentB2buaMappingStore,
        }[name]
    if name == "B2BUASessionIdFactory":
        from .b2bua_session_id_factory import B2BUASessionIdFactory

        return B2BUASessionIdFactory
    if name == "B2BUASessionResolver":
        from .b2bua_session_resolver_service import B2BUASessionResolver

        return B2BUASessionResolver
    if name == "DefaultClientSessionIdExtractor":
        from .client_session_id_extractor_service import DefaultClientSessionIdExtractor

        return DefaultClientSessionIdExtractor
    if name == "JsonRepairService":
        from .json_repair_service import JsonRepairService

        return JsonRepairService
    if name == "StructuredOutputMiddleware":
        from .structured_output_middleware import StructuredOutputMiddleware

        return StructuredOutputMiddleware

    # Fallback: try importing as a submodule for names that look like modules.
    import importlib
    import sys as _sys

    try:
        module = importlib.import_module(f".{name}", package=__package__)
        _sys.modules.setdefault(f"{__package__}.{name}", module)
        return module
    except ImportError:
        pass

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
