"""Quality Verifier turn ledger backed by the service provider.

Resolves :class:`IRequestProcessor` lazily on reset so DI can construct
:class:`ResponseProcessor` and :class:`BackendRequestManager` without cycles.
"""

from __future__ import annotations

from typing import Any, cast

from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.request_processor_interface import IRequestProcessor


class ProviderBackedQualityVerifierTurnLedger:
    """Delegates eligible-turn resets to :class:`RequestProcessor` via the provider."""

    def __init__(self, provider: IServiceProvider) -> None:
        self._provider = provider

    def reset_quality_verifier_eligible_turn_count(
        self, session_key: str, session: Any | None
    ) -> None:
        rp: Any = self._provider.get_required_service(
            cast(type, IRequestProcessor)
        )
        rp.reset_quality_verifier_eligible_turn_count(session_key, session)
