from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import INotificationService
from src.core.interfaces.quality_verifier_service_interface import (
    IQualityVerifierServiceFactory,
)
from src.core.services.quality_verifier_service import QualityVerifierService


class DefaultQualityVerifierServiceFactory(IQualityVerifierServiceFactory):
    """Default implementation for creating QualityVerifierService instances.

    This keeps Quality Verifier wiring optional: if it is disabled (empty model_spec),
    QualityVerifierService will no-op.
    """

    def create(
        self,
        model_spec: str,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service: INotificationService | None = None,
    ) -> QualityVerifierService:
        return QualityVerifierService(
            model_spec,
            max_history,
            max_consecutive_failures=max_consecutive_failures,
            cooldown_seconds=cooldown_seconds,
            notification_service=notification_service,
        )
