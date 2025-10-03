"""Default stage registry for staged application initialization."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .backend import BackendStage
from .base import InitializationStage
from .command import CommandStage
from .controller import ControllerStage
from .core_services import CoreServicesStage
from .infrastructure import InfrastructureStage
from .processor import ProcessorStage


class DefaultApplicationStages:
    """Expose the default initialization stages in dependency order."""

    def __init__(self) -> None:
        self._stages: tuple[InitializationStage, ...] = (
            InfrastructureStage(),
            CoreServicesStage(),
            BackendStage(),
            CommandStage(),
            ProcessorStage(),
            ControllerStage(),
        )

    def __iter__(self) -> Iterable[InitializationStage]:
        return iter(self._stages)

    def as_sequence(self) -> Sequence[InitializationStage]:
        """Return the stages as an immutable sequence."""
        return self._stages

    def get_stages(self) -> list[InitializationStage]:
        """Return a new list with the default stages."""
        return list(self._stages)
