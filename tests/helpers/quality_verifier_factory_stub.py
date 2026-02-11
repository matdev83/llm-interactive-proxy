from __future__ import annotations

from src.core.interfaces.quality_verifier_service_interface import (
    IQualityVerifierServiceFactory,
)
from src.core.services.quality_verifier_service import QualityVerifierService


class QualityVerifierFactoryStub(IQualityVerifierServiceFactory):
    """Test helper that builds QualityVerifierService instances."""

    def __init__(self, default_spec: str = "openai:gpt-4o-mini") -> None:
        self._default_spec = default_spec

    def create(
        self,
        model_spec: str,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service=None,
    ) -> QualityVerifierService:
        spec = model_spec or self._default_spec
        return QualityVerifierService(
            spec,
            max_history=max_history,
            max_consecutive_failures=max_consecutive_failures,
            cooldown_seconds=cooldown_seconds,
            notification_service=notification_service,
        )
