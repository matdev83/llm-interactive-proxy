
from pathlib import Path

file_path = Path("src/core/services/backend_service.py")
content = file_path.read_text(encoding="utf-8")

# Add missing imports
target = """from src.core.interfaces.wire_capture_interface import IWireCapture"""
new_imports = """from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)"""

if target in content and "IExceptionNormalizer" not in content:
    content = content.replace(target, new_imports)
    file_path.write_text(content, encoding="utf-8")
    print("Added missing interface imports")
else:
    print("Imports check failed or already present")
    if "IExceptionNormalizer" in content:
        print("IExceptionNormalizer is present")
    if target not in content:
        print("Target IWireCapture import not found")
