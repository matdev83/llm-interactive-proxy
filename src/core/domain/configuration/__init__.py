# Configuration package

from .backend_config import BackendConfiguration
from .loop_detection_config import LoopDetectionConfiguration
from .reasoning_config import ReasoningConfiguration

# Legacy aliases for backward compatibility
BackendConfig = BackendConfiguration
LoopDetectionConfig = LoopDetectionConfiguration
ReasoningConfig = ReasoningConfiguration

__all__ = [
    "BackendConfig",
    "BackendConfiguration",
    "LoopDetectionConfig",
    "LoopDetectionConfiguration",
    "ReasoningConfig",
    "ReasoningConfiguration",
]
