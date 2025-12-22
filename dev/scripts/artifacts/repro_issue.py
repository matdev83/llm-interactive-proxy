import logging
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from unittest.mock import MagicMock

from src.core.config.app_config import AppConfig
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)

# Configure logging
logging.basicConfig(level=logging.DEBUG)


def test_resolution():
    # Mock dependencies
    app_config = MagicMock(spec=AppConfig)
    app_config.session.project_dir_resolution_mode = "deterministic"
    app_config.session.project_dir_resolution_model = None

    service = ProjectDirectoryResolutionService(app_config, MagicMock(), MagicMock())

    prompt = r"""
    I am working on these files:
    C:\Users\Mateusz\Projects\Java\Project1\tests
    C:\Users\Mateusz\Projects\Java\Project1\tests\unit
    C:\Users\Mateusz\Projects\Java\Project1\bin
    C:\Users\Mateusz\Projects\Java\Project1\source\package1
    """

    print(f"Analyzing prompt: {prompt}")
    result = service._find_absolute_path_in_prompt(prompt)
    print(f"Result: {result}")

    expected = r"C:\Users\Mateusz\Projects\Java\Project1"

    if result and (result == expected or result.rstrip("\\") == expected):
        print("SUCCESS: Detected correct common root.")
    else:
        print(f"FAILURE: Expected {expected}, got {result}")


if __name__ == "__main__":
    test_resolution()
