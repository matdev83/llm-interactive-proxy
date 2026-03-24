"""Session detection for KiloCode/RooCode XML compatibility in OpenAI Codex connector."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from cachetools import TTLCache  # type: ignore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Import telemetry
try:
    from src.connectors._openai_codex_telemetry import (
        CompatibilityTelemetry,
        get_telemetry,
    )
except ImportError:
    # Fallback if telemetry module is not available
    # Create a minimal stub CompatibilityTelemetry class
    class _FallbackCompatibilityTelemetry:  # type: ignore[no-redef]
        """Fallback stub for telemetry when module is not available."""

        def log_detection_event(self, *args: Any, **kwargs: Any) -> None:
            pass

        def log_translation_event(self, *args: Any, **kwargs: Any) -> None:
            pass

        def log_error_event(self, *args: Any, **kwargs: Any) -> None:
            pass

    _fallback_telemetry = _FallbackCompatibilityTelemetry()
    CompatibilityTelemetry = _FallbackCompatibilityTelemetry  # type: ignore[assignment,misc]

    def get_telemetry() -> CompatibilityTelemetry:  # type: ignore[assignment]
        """Fallback telemetry getter."""
        return _fallback_telemetry  # type: ignore[return-value]


@dataclass(frozen=True)
class CacheStats:
    """Statistics for the session detector cache."""

    total_entries: int
    hits: int
    misses: int
    hit_rate: float


@dataclass
class DetectionResult:
    """Result of KiloCode/RooCode XML compatibility detection.

    Note:
    The public field name remains ``is_kilocode`` for backward compatibility with
    the existing connector contracts. Semantically it means the request should use
    the KiloCode/RooCode XML compatibility layer. Vanilla **Cline** is excluded
    (native Codex tooling); Roo ``*cline`` variants remain included.
    """

    is_kilocode: bool
    detection_method: str  # "metadata", "header", "heuristic", "cached"
    confidence: float  # 0.0 to 1.0
    agent_string: str | None
    timestamp: float


class SessionDetector:
    """Detect KiloCode/RooCode XML compatibility clients with caching for performance."""

    KILOCODE_ALIASES = {
        "kilocode",
        "kilo-code",
        "kilo_code",
        "kilocode.ai",
        "kiloc",
        "kilo",
    }
    ROOCODE_FAMILY_ALIASES = {
        "roo",
        "roocode",
        "roo-code",
        "roo_code",
        "roo cline",
        "roo-cline",
        "roo_cline",
    }
    # Vanilla Cline is intentionally excluded (false-positive prevention; native Codex path).
    KILOCODE_COMPAT_METADATA_ALIASES = frozenset(
        KILOCODE_ALIASES | ROOCODE_FAMILY_ALIASES
    )

    # XML tags that are characteristic of KiloCode clients
    KILOCODE_XML_TAGS = {
        "<read_file>",
        "<list_files>",
        "<execute_command>",
        "<codebase_search>",
        "<search_files>",
        "<use_mcp_tool>",
        "<access_mcp_resource>",
        "<attempt_completion>",
        "<ask_followup_question>",
        "<search_and_replace>",
        "<write_to_file>",
        "<insert_content>",
        "<edit_file>",
    }

    def __init__(
        self,
        cache_ttl_seconds: int = 3600,
        heuristic_threshold: int = 2,
        max_cache_size: int = 10000,
    ):
        """Initialize the session detector.

        Args:
            cache_ttl_seconds: Time-to-live for cached detection results
            heuristic_threshold: Minimum number of XML tags to trigger heuristic detection
            max_cache_size: Maximum number of entries to keep in cache
        """
        self._cache: MutableMapping[str, DetectionResult] = TTLCache(
            maxsize=max_cache_size, ttl=cache_ttl_seconds
        )
        self._cache_lock = asyncio.Lock()
        self._cache_ttl = cache_ttl_seconds
        self._heuristic_threshold = heuristic_threshold
        # Cache statistics tracking
        self._cache_hits = 0
        self._cache_misses = 0

    async def detect(
        self,
        request_data: Any,
        metadata: Mapping[str, Any] | None,
        session_id: str,
        backend: str,
        agent: str | None = None,
    ) -> DetectionResult:
        """Detect if request is from a Cline-like XML client.

        Args:
            request_data: The request data object
            metadata: Optional metadata dictionary
            session_id: Session identifier for caching
            backend: Backend name for cache invalidation
            agent: Optional agent identifier for cache invalidation

        Returns:
            DetectionResult with detection outcome and metadata
        """
        # Use default agent if not provided
        if agent is None:
            agent = "default"

        # Check cache first
        cache_key = self._build_cache_key(session_id, backend, agent)
        async with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                # Increment cache hit counter
                self._cache_hits += 1

                logger.debug(
                    "Using cached KiloCode detection result for session %s: %s",
                    session_id,
                    cached.is_kilocode,
                )

                # Log telemetry for cache hit
                telemetry = get_telemetry()
                if telemetry:
                    telemetry.log_detection_event(
                        session_id=session_id,
                        is_kilocode=cached.is_kilocode,
                        detection_method="cached",
                        confidence=cached.confidence,
                        duration_ms=0.0,  # Cache hits are essentially instant
                        agent_string=cached.agent_string,
                    )

                return DetectionResult(
                    is_kilocode=cached.is_kilocode,
                    detection_method="cached",
                    confidence=cached.confidence,
                    agent_string=cached.agent_string,
                    timestamp=cached.timestamp,
                )

            # Increment cache miss counter
            self._cache_misses += 1

        # Perform detection
        start_time = time.time()

        # Method 1: Check metadata
        result = self._check_metadata(metadata)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via metadata in %.2fms: %s",
                detection_time,
                result.agent_string,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Method 2: Check headers
        result = self._check_headers(request_data)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via headers in %.2fms: %s",
                detection_time,
                result.agent_string,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Method 3: Check payload heuristics
        result = self._check_payload_heuristics(request_data)
        if result:
            detection_time = (time.time() - start_time) * 1000
            logger.debug(
                "KiloCode detected via heuristics in %.2fms (confidence: %.2f)",
                detection_time,
                result.confidence,
            )
            await self._cache_result(cache_key, result)

            # Log telemetry
            telemetry = get_telemetry()
            if telemetry:
                telemetry.log_detection_event(
                    session_id=session_id,
                    is_kilocode=True,
                    detection_method=result.detection_method,
                    confidence=result.confidence,
                    duration_ms=detection_time,
                    agent_string=result.agent_string,
                )

            return result

        # Not detected as a Cline-like XML client
        detection_time = (time.time() - start_time) * 1000
        logger.debug(
            "KiloCode not detected for session %s (%.2fms)", session_id, detection_time
        )
        result = DetectionResult(
            is_kilocode=False,
            detection_method="none",
            confidence=0.0,
            agent_string=None,
            timestamp=time.time(),
        )
        await self._cache_result(cache_key, result)

        # Log telemetry for non-detection
        telemetry = get_telemetry()
        if telemetry:
            telemetry.log_detection_event(
                session_id=session_id,
                is_kilocode=False,
                detection_method="none",
                confidence=0.0,
                duration_ms=detection_time,
                agent_string=None,
            )

        return result

    def _check_metadata(
        self, metadata: Mapping[str, Any] | None
    ) -> DetectionResult | None:
        """Check explicit agent metadata for Cline-like client identification.

        Args:
            metadata: Request metadata dictionary

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        if not metadata or not isinstance(metadata, Mapping):
            return None

        agent = metadata.get("agent")
        if not isinstance(agent, str):
            return None

        agent_lower = agent.lower().strip()
        if not agent_lower:
            return None

        normalized = self._normalize_agent_string(agent_lower)

        if self._matches_kilocode_compat_agent(agent_lower, normalized):
            return DetectionResult(
                is_kilocode=True,
                detection_method="metadata",
                confidence=1.0,
                agent_string=agent,
                timestamp=time.time(),
            )

        if normalized.startswith(("kilocode", "roocode")):
            return DetectionResult(
                is_kilocode=True,
                detection_method="metadata",
                confidence=0.95,
                agent_string=agent,
                timestamp=time.time(),
            )

        return None

    def _check_headers(self, request_data: Any) -> DetectionResult | None:
        """Check HTTP User-Agent header for Cline-like client identification.

        Args:
            request_data: The request data object

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        # Try to extract User-Agent from various possible locations
        user_agent = None

        # Check if request_data has headers attribute
        if hasattr(request_data, "headers"):
            headers = request_data.headers
            if isinstance(headers, Mapping):
                user_agent = headers.get("User-Agent") or headers.get("user-agent")

        # Check extra_body for headers
        if not user_agent and hasattr(request_data, "extra_body"):
            extra_body = request_data.extra_body
            if isinstance(extra_body, Mapping):
                headers = extra_body.get("headers")
                if isinstance(headers, Mapping):
                    user_agent = headers.get("User-Agent") or headers.get("user-agent")

        if not user_agent or not isinstance(user_agent, str):
            return None

        user_agent_lower = user_agent.lower().strip()
        if not user_agent_lower:
            return None

        normalized = self._normalize_agent_string(user_agent_lower)

        if self._user_agent_matches_kilocode_compat(user_agent_lower, normalized):
            return DetectionResult(
                is_kilocode=True,
                detection_method="header",
                confidence=0.9,
                agent_string=user_agent,
                timestamp=time.time(),
            )

        if any(token in normalized for token in ("kilocode", "roocode")):
            return DetectionResult(
                is_kilocode=True,
                detection_method="header",
                confidence=0.85,
                agent_string=user_agent,
                timestamp=time.time(),
            )

        return None

    def _check_payload_heuristics(self, request_data: Any) -> DetectionResult | None:
        """Check for Cline-like XML tags in request payload.

        Args:
            request_data: The request data object

        Returns:
            DetectionResult if KiloCode detected, None otherwise
        """
        # Extract messages from request
        messages = None
        if hasattr(request_data, "messages"):
            messages = request_data.messages
        elif isinstance(request_data, Mapping):
            messages = request_data.get("messages")

        if not messages:
            return None

        # Count XML tag occurrences in message content
        tag_count = 0
        found_tags: set[str] = set()

        for message in messages:
            content = None
            if hasattr(message, "content"):
                content = message.content
            elif isinstance(message, Mapping):
                content = message.get("content")

            if not content:
                continue

            # Convert content to string
            content_str = str(content).lower()

            # Check for KiloCode XML tags
            for tag in self.KILOCODE_XML_TAGS:
                if tag.lower() in content_str:
                    tag_count += 1
                    found_tags.add(tag)

        # If we found enough tags, consider it a Cline-like XML client
        if tag_count >= self._heuristic_threshold:
            confidence = min(0.7 + (tag_count * 0.05), 0.95)
            logger.debug(
                "Heuristic detection found %d KiloCode XML tags: %s",
                tag_count,
                found_tags,
            )
            return DetectionResult(
                is_kilocode=True,
                detection_method="heuristic",
                confidence=confidence,
                agent_string=None,
                timestamp=time.time(),
            )

        return None

    @staticmethod
    def _normalize_agent_string(value: str) -> str:
        return (
            value.lower()
            .replace("-", "")
            .replace("_", "")
            .replace(".", "")
            .replace(" ", "")
        )

    def _matches_kilocode_compat_agent(self, agent_lower: str, normalized: str) -> bool:
        if agent_lower in self.KILOCODE_COMPAT_METADATA_ALIASES:
            return True
        return normalized in {
            "kilocode",
            "kiloc",
            "kilo",
            "roo",
            "roocode",
            "roocline",
        }

    def _user_agent_matches_kilocode_compat(
        self, user_agent_lower: str, normalized: str
    ) -> bool:
        if any(
            alias in user_agent_lower for alias in self.KILOCODE_COMPAT_METADATA_ALIASES
        ):
            return True
        return any(
            token in normalized
            for token in ("kilocode", "kiloc", "roocode", "roocline")
        )

    async def invalidate_cache(self, session_id: str, backend: str) -> None:
        """Clear cached detection result for a session.

        Args:
            session_id: Session identifier
            backend: Backend name
        """
        cache_key = self._build_cache_key(session_id, backend)
        async with self._cache_lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                logger.debug(
                    "Invalidated KiloCode detection cache for session %s", session_id
                )

    async def _cache_result(self, cache_key: str, result: DetectionResult) -> None:
        """Store detection result in cache.

        Args:
            cache_key: Cache key
            result: Detection result to cache
        """
        async with self._cache_lock:
            self._cache[cache_key] = result

    @staticmethod
    def _build_cache_key(session_id: str, backend: str, agent: str = "default") -> str:
        """Build cache key from session, backend, and agent.

        Args:
            session_id: Session identifier
            backend: Backend name
            agent: Agent identifier (defaults to "default")

        Returns:
            Cache key string (SHA256 hash for consistency)
        """
        import hashlib

        # Use SHA256 hash for consistent key generation
        key_string = f"{session_id}:{backend}:{agent}"
        return hashlib.sha256(key_string.encode()).hexdigest()

    def invalidate_cache_for_backend_change(
        self, old_backend: str, new_backend: str
    ) -> None:
        """Invalidate cache entries when backend configuration changes.

        Args:
            old_backend: Previous backend name
            new_backend: New backend name
        """
        # Synchronous cache clear - safe since TTLCache is thread-safe
        size_before = len(self._cache)
        self._cache.clear()

        logger.info(
            "Cache invalidated for backend change: %s → %s (%d entries cleared)",
            old_backend,
            new_backend,
            size_before,
        )

    def invalidate_cache_for_agent_change(self, old_agent: str, new_agent: str) -> None:
        """Invalidate cache entries when agent configuration changes.

        Args:
            old_agent: Previous agent identifier
            new_agent: New agent identifier
        """
        # Synchronous cache clear - safe since TTLCache is thread-safe
        size_before = len(self._cache)
        self._cache.clear()

        logger.info(
            "Cache invalidated for agent change: %s → %s (%d entries cleared)",
            old_agent,
            new_agent,
            size_before,
        )

    def get_cache_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats dataclass containing cache performance metrics.
        """
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0.0

        return CacheStats(
            total_entries=len(self._cache),
            hits=self._cache_hits,
            misses=self._cache_misses,
            hit_rate=hit_rate,
        )
