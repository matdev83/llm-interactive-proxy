"""
Proof-of-concept test to demonstrate the project root detection fix.
This test verifies that .venv/Scripts paths don't become the project root.
"""
import pytest
from unittest.mock import AsyncMock
from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


@pytest.mark.asyncio
async def test_venv_scripts_should_not_be_project_root():
    r"""
    PROOF: This test demonstrates the fix for the exact scenario from the logs:
    - Multiple paths detected including .venv\Scripts  
    - Should find common directory C:\Users\Mateusz\source\repos\patch-file-mcp-fork
    - NOT C:\Users\Mateusz\source\repos\patch-file-mcp-fork\.venv\Scripts
    """
    # Setup
    config = AppConfig(
        session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4",
        )
    )
    mock_backend = AsyncMock()
    mock_session = AsyncMock()
    session = Session(session_id="proof-test", state=SessionState())
    service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

    # Simulate the exact scenario from the logs
    prompt = (
        "Files in the project: "
        "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\src\\main.py, "
        "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\tests\\test.py, "
        "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\.venv\\Scripts\\python.exe"
    )
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=prompt)]
    )

    # Execute
    await service.maybe_resolve_project_directory(session, request)

    # Verify - should be the project root, NOT .venv\Scripts
    assert session.state.project_dir == "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork"
    assert session.state.project_dir_resolution_attempted is True
    
    print(f"\n✅ PROOF: Detected project dir = {session.state.project_dir}")
    print(f"✅ PROOF: NOT .venv\\Scripts - the fix works!")


@pytest.mark.asyncio  
async def test_unix_common_directory_detection():
    """Additional proof for Unix paths."""
    config = AppConfig(
        session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4",
        )
    )
    mock_backend = AsyncMock()
    mock_session = AsyncMock()
    session = Session(session_id="unix-proof", state=SessionState())
    service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

    prompt = (
        "/home/user/myproject/src/app.py, "
        "/home/user/myproject/lib/utils.py, "
        "/home/user/myproject/.venv/bin/python"
    )
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=prompt)]
    )

    await service.maybe_resolve_project_directory(session, request)

    assert session.state.project_dir == "/home/user/myproject"
    print(f"\n✅ PROOF: Unix paths work too = {session.state.project_dir}")
