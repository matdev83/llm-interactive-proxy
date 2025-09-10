from src.core.app.stages.backend import BackendStage
from src.core.app.stages.command import CommandStage
from src.core.app.stages.controller import ControllerStage
from src.core.app.stages.core_services import CoreServicesStage
from src.core.app.stages.infrastructure import InfrastructureStage
from src.core.app.stages.processor import ProcessorStage


class DefaultApplicationStages:
    """
    Defines the default set of application initialization stages.
    """

    ALL = [
        CoreServicesStage,
        InfrastructureStage,
        BackendStage,
        CommandStage,
        ProcessorStage,
        ControllerStage,
    ]
