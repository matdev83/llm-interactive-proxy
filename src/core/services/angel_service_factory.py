from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.interfaces.notification_service_interface import INotificationService
from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.services.angel_service import AngelService


class DefaultAngelServiceFactory(IAngelServiceFactory):
    """Default implementation for creating AngelService instances.

    This keeps Angel wiring optional: if Angel is disabled (empty model_spec),
    AngelService will no-op.
    """

    def create(
        self,
        model_spec: str,
        max_history: int | None = None,
        max_consecutive_failures: int = 5,
        cooldown_seconds: int = 300,
        notification_service: INotificationService | None = None,
    ) -> AngelService:
        return AngelService(
            model_spec,
            max_history,
            max_consecutive_failures=max_consecutive_failures,
            cooldown_seconds=cooldown_seconds,
            notification_service=notification_service,
        )
