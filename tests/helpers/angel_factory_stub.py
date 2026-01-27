from __future__ import annotations

from src.core.interfaces.angel_service_interface import IAngelServiceFactory
from src.core.services.angel_service import AngelService


class AngelFactoryStub(IAngelServiceFactory):
    """Test helper that builds AngelService instances."""

    def __init__(self, default_spec: str = "openai:gpt-4o-mini") -> None:
        self._default_spec = default_spec

    def create(self, model_spec: str, max_history: int | None = None) -> AngelService:
        spec = model_spec or self._default_spec
        return AngelService(spec, max_history=max_history)
