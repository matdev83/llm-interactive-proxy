from __future__ import annotations

from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.services.angel_service import AngelService


class DefaultAngelServiceFactory(IAngelServiceFactory):
    """Default implementation for creating AngelService instances.

    This keeps Angel wiring optional: if Angel is disabled (empty model_spec),
    AngelService will no-op.
    """

    def create(self, model_spec: str, max_history: int | None = None) -> AngelService:
        return AngelService(model_spec, max_history)
