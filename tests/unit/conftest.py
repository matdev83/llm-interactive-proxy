import re

import pytest
from fastapi import FastAPI
from src.command_config import CommandProcessorConfig
from src.command_parser import CommandParser
from src.core.domain.session import SessionState, SessionStateAdapter
from src.core.services.command_service import CommandRegistry

from tests.unit.mock_commands import (
    get_mock_commands,
)


@pytest.fixture
def command_registry() -> CommandRegistry:
    """Provides a CommandRegistry instance with mock handlers."""
    registry = CommandRegistry()
    mock_commands = get_mock_commands()
    for command in mock_commands.values():
        registry.register(command)
    return registry


@pytest.fixture
def command_parser(command_registry: CommandRegistry) -> CommandParser:
    """Provides a CommandParser instance with mock handlers and a properly initialized command_processor."""
    # Create a mock proxy state
    mock_proxy_state = SessionStateAdapter(SessionState())
    
    # Create a mock FastAPI app
    mock_app = FastAPI()
    
    # Create a command pattern
    command_pattern = re.compile(r"!/(\w+)(?:\(([^)]*)\))?")
    
    # Create a config object
    config = CommandProcessorConfig(
        proxy_state=mock_proxy_state,
        app=mock_app,
        command_pattern=command_pattern,
        handlers=command_registry.get_all(),
        preserve_unknown=True,
        command_results=[]
    )
    
    # Create a CommandParser with the config
    parser = CommandParser(config=config, command_registry=command_registry)
    
    # Ensure command_processor is initialized
    if parser.command_processor is None:
        raise RuntimeError("Failed to initialize CommandProcessor. This is a test setup issue.")
    
    return parser
