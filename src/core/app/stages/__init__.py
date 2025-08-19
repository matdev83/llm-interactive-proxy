"""
Initialization stages for the application builder pattern.

This package contains the staged initialization system that replaces
the complex monolithic ApplicationFactory approach.
"""

from .backend import BackendStage
from .base import InitializationStage
from .command import CommandStage
from .controller import ControllerStage
from .core_services import CoreServicesStage
from .infrastructure import InfrastructureStage
from .processor import ProcessorStage

__all__ = [
    "BackendStage",
    "CommandStage",
    "ControllerStage",
    "CoreServicesStage",
    "InfrastructureStage",
    "InitializationStage",
    "ProcessorStage",
]
