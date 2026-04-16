from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from src.core.url_safety import assert_url_safe_for_egress

if TYPE_CHECKING:
    from src.core.config.models.misc import ModelRegistryConfig
    from src.core.services.model_catalog_service import ModelCatalogService

logger = logging.getLogger(__name__)


class ModelCatalogUpdater:
    """Service for periodically updating the model catalog from an external source."""

    def __init__(
        self,
        config: ModelRegistryConfig,
        catalog_service: ModelCatalogService,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._catalog_service = catalog_service
        self._http_client = http_client or httpx.AsyncClient(timeout=30.0)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background update task."""
        if not self._config.download_enabled:
            logger.info("Model catalog downloads are disabled.")
            return

        if self._task is not None:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._update_loop(), name="model_catalog_updater"
        )
        logger.info("Model catalog updater started.")

    async def stop(self) -> None:
        """Stop the background update task."""
        if self._task is None:
            return

        from contextlib import suppress

        self._stop_event.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

        # Close HTTP client if we own it
        if self._http_client is not None:
            await self._http_client.aclose()

        logger.info("Model catalog updater stopped.")

    async def _update_loop(self) -> None:
        """Main update loop."""
        # Initial update on startup
        await self.update_now()

        while not self._stop_event.is_set():
            try:
                # Wait for the next interval or stop event
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(self._config.update_interval_seconds),
                )
                if self._stop_event.is_set():
                    break
            except asyncio.TimeoutError:
                # Interval reached, perform update
                await self.update_now()

    async def update_now(self) -> bool:
        """Perform an immediate update of the model catalog."""
        url = self._config.url
        cache_path = Path(self._config.cache_path)

        # Ensure parent directory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Fetching model catalog from %s", url)

            assert_url_safe_for_egress(url)

            response = await self._http_client.get(url)
            response.raise_for_status()

            # Basic validation: must be a dict
            data = response.json()
            if not isinstance(data, dict) or not data:
                logger.warning(
                    "Invalid model catalog format received from %s (not a dict or empty)",
                    url,
                )
                return False

            # Save to cache
            temp_path = cache_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            # Atomic swap
            temp_path.replace(cache_path)

            # Reload catalog in service
            self._catalog_service.load_catalog()

            if logger.isEnabledFor(logging.INFO):
                logger.info("Successfully updated model catalog from %s", url)
            return True

        except Exception as e:
            logger.error("Failed to update model catalog from %s: %s", url, e)
            return False
