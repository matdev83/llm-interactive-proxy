from importlib import reload

import pytest
import src.core.domain.commands.loop_detection_commands as loop_detection_commands


@pytest.fixture(autouse=True)
def ensure_clean_loop_detection_commands_module():
    """Ensure the loop detection commands module is clean for all tests in this package."""
    reload(loop_detection_commands)
    yield
    reload(loop_detection_commands)
