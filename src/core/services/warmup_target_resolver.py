"""Warm-up target resolver with backend-specific account fan-out."""

from __future__ import annotations

import inspect
import logging

from src.core.common.exceptions import BackendError
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.warmup_target_resolver_interface import IWarmupTargetResolver

logger = logging.getLogger(__name__)


class WarmupTargetResolver(IWarmupTargetResolver):
    """Resolve warm-up fan-out targets for multi-account backends."""

    def __init__(
        self, backend_lifecycle_manager: IBackendLifecycleManager | None
    ) -> None:
        self._backend_lifecycle_manager = backend_lifecycle_manager

    async def resolve_target_accounts(self, backend_type: str) -> list[str]:
        if backend_type not in ("openai-codex", "openai-codex-v2"):
            return []
        if self._backend_lifecycle_manager is None:
            return []

        try:
            backend = await self._backend_lifecycle_manager.get_or_create(
                backend_type,
                session_id="usage-window-warmup:fanout",
            )
        except BackendError as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping warm-up account fan-out for '%s': %s",
                    backend_type,
                    exc,
                    exc_info=True,
                )
            return []

        list_accounts = getattr(backend, "list_managed_oauth_account_ids", None)
        if not callable(list_accounts):
            return []

        result = list_accounts()
        account_ids = await result if inspect.isawaitable(result) else result
        if not isinstance(account_ids, list):
            return []
        eligible_accounts = [
            account_id
            for account_id in account_ids
            if isinstance(account_id, str) and account_id
        ]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Resolved %d warm-up account targets for backend '%s'",
                len(eligible_accounts),
                backend_type,
            )
        return eligible_accounts
