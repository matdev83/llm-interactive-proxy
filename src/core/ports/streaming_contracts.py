"""
Streaming pipeline contracts and interfaces.

This module serves as a compatibility facade that re-exports streaming interfaces
and domain models for backward compatibility. The actual implementations have
been moved to focused modules:

- Interfaces: src/core/ports/streaming/interfaces.py
- Base normalizer: src/core/ports/streaming/normalizer_base.py
- Domain models: src/core/domain/streaming/
- Error mapping: src/core/services/streaming/error_mapping.py

This facade ensures that all existing imports continue to work while maintaining
clear boundaries between ports, domain, and services layers.
"""

from __future__ import annotations

from typing import TypeAlias

# Re-export domain models for backward compatibility
from src.core.domain.streaming.sentinels import SentinelManager
from src.core.domain.streaming.stop_chunk_with_usage import (
    StopChunkWithUsage,
    UsageChunkLeakError,
)
from src.core.domain.streaming.streaming_content import StreamingContent

# Re-export interfaces from ports/streaming module
from src.core.ports.streaming.interfaces import (
    IProviderStreamNormalizer,
    IStreamAssembler,
    IStreamProcessor,
    StreamProducer,
)

# Re-export IProviderStreamNormalizer as IStreamNormalizer for backward compatibility
IStreamNormalizer: TypeAlias = IProviderStreamNormalizer

# Re-export base normalizer from ports/streaming module
from src.core.ports.streaming.normalizer_base import BaseStreamNormalizer

# Re-export error mapping from services layer
# Services layer may import httpx, but ports layer does not (boundary enforcement)
from src.core.services.streaming.error_mapping import (
    StreamingErrorMapper,
    handle_streaming_error,
)

__all__ = [
    "StreamProducer",
    "IStreamNormalizer",
    "BaseStreamNormalizer",
    "IStreamProcessor",
    "IStreamAssembler",
    "StreamingContent",
    "StopChunkWithUsage",
    "UsageChunkLeakError",
    "SentinelManager",
    "StreamingErrorMapper",
    "handle_streaming_error",
]
