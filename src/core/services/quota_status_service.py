"""Service for tracking global backend quotas and rate limits."""

from __future__ import annotations

import logging
import threading
from typing import Any, Mapping

logger = logging.getLogger(__name__)


class QuotaStatusService:
    """Centralized service for monitoring backend usage quotas.

    This service maintains a global view of rate limits and usage percentages
    across all backend instances, allowing the proxy to provide consistent
    quota information even when specific instances haven't made recent requests.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self._quotas: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()
        self._repository = repository

    def set_repository(self, repository: Any) -> None:
        """Set the repository for persistent storage and load existing quotas.

        Args:
            repository: BackendQuotaRepository instance
        """
        self._repository = repository
        
        # Load existing quotas from DB
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # We need to load quotas but we are in a sync method
                # Spawn a task to load them
                loop.create_task(self._load_quotas())
        except RuntimeError:
            pass

    async def _load_quotas(self) -> None:
        """Load quotas from the repository."""
        if not self._repository:
            return
        
        try:
            quotas = await self._repository.get_all_quotas()
            with self._lock:
                # Merge loaded quotas, but don't overwrite newer in-memory values
                for b_type, headers in quotas.items():
                    if b_type not in self._quotas:
                        self._quotas[b_type] = headers
                    else:
                        # Only add missing keys
                        for k, v in headers.items():
                            self._quotas[b_type].setdefault(k, v)
            
            if logger.isEnabledFor(logging.INFO):
                logger.info("Loaded quotas for %d backends from database", len(quotas))
        except Exception as e:
            logger.warning("Failed to load quotas from database: %s", e)

    def update_quota(self, backend_type: str, headers: Mapping[str, str]) -> None:
        """Update captured quota headers for a backend.

        Args:
            backend_type: The type of backend (e.g., "openai")
            headers: Response headers containing quota information
        """
        quota_headers = {}
        quota_prefixes = ("x-codex-", "x-ratelimit-", "x-usage-")

        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower.startswith(quota_prefixes):
                quota_headers[k_lower] = str(v)

        if not quota_headers:
            return

        with self._lock:
            if backend_type not in self._quotas:
                self._quotas[backend_type] = {}
            
            # Update only if values have changed or are new
            self._quotas[backend_type].update(quota_headers)
            
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Updated quota for %s: %s", backend_type, list(quota_headers.keys())
                )

        # Persist to database if repository is available
        if self._repository:
            import asyncio
            try:
                # Get current merged headers for this backend type
                with self._lock:
                    current_quota = dict(self._quotas[backend_type])
                
                # Spawn a background task to upsert to DB
                # Note: We use asyncio.create_task if a loop is running
                try:
                    loop = asyncio.get_running_loop()
                    if loop.is_running():
                        loop.create_task(self._repository.upsert_quota(backend_type, current_quota))
                except RuntimeError:
                    # No running loop, skip persistent update
                    pass
            except Exception as e:
                logger.warning("Failed to persist quota update: %s", e)

    def get_quota_headers(self, backend_type: str | None = None) -> dict[str, str]:
        """Get all captured quota headers.

        Args:
            backend_type: Optional backend type to filter by. 
                         If None, returns merged headers from all backends.

        Returns:
            Dictionary of quota headers
        """
        with self._lock:
            if backend_type:
                return dict(self._quotas.get(backend_type, {}))
            
            # Merge all quotas (OpenAI/Codex usually takes priority for this proxy)
            merged = {}
            # Sort keys to ensure deterministic merging if multiple backends use same headers
            for b_type in sorted(self._quotas.keys()):
                merged.update(self._quotas[b_type])
            return merged

    def get_all_quotas(self) -> dict[str, dict[str, str]]:
        """Get all captured quotas grouped by backend type."""
        with self._lock:
            return {k: dict(v) for k, v in self._quotas.items()}


# Global singleton instance for easy access
_instance = QuotaStatusService()


def get_quota_status_service() -> QuotaStatusService:
    """Get the global quota status service instance."""
    return _instance
