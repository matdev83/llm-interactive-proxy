#!/usr/bin/env python3
r"""
Final verification: Test fix against the ACTUAL CBOR scenario.

The agent was working on improving the proxy itself:
- Project root: C:\Users\Mateusz\source\repos\llm-interactive-proxy
- Should detect: C:\Users\Mateusz\source\repos\llm-interactive-proxy
- Should NOT detect: C:\Users\Mateusz\source\repos\llm-interactive-proxy\.venv\Scripts
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


async def test_actual_cbor_scenario():
    """Test with the actual scenario from CBOR capture."""
    
    print("=" * 80)
    print("ACTUAL CBOR SCENARIO VERIFICATION")
    print("=" * 80)
    print()
    print("Scenario: Agent working on proxy project itself")
    print(r"Expected: C:\Users\Mateusz\source\repos\llm-interactive-proxy")
    print(r"NOT:      C:\Users\Mateusz\source\repos\llm-interactive-proxy\.venv\Scripts")
    print()
    
    # Simulated prompt that would contain references to files in the proxy project
    # including .venv paths
    prompt = r"""
    I need help with this Python project at C:\Users\Mateusz\source\repos\llm-interactive-proxy
    
    The project structure includes:
    - C:\Users\Mateusz\source\repos\llm-interactive-proxy\src\core\services\project_directory_resolution_service.py
    - C:\Users\Mateusz\source\repos\llm-interactive-proxy\tests\unit\services\test_project_directory_resolution_service.py
    - C:\Users\Mateusz\source\repos\llm-interactive-proxy\.venv\Scripts\python.exe
    
    Please help me analyze the project directory resolution logic.
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
    session = Session(session_id="actual-cbor-test", state=SessionState())
    
    service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)
    
    # Run detection
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content=prompt)]
    )
    
    print("🔍 Running project directory detection...")
    await service.maybe_resolve_project_directory(session, request)
    
    detected = session.state.project_dir
    
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()
    
    expected = "C:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy"
    wrong = "C:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy\\.venv\\Scripts"
    
    print(f"Expected: {expected}")
    print(f"Detected: {detected}")
    print()
    
    # Verification
    if detected == expected:
        print("✅ SUCCESS! Correctly detected project root!")
        print("✅ .venv\\Scripts was properly rejected!")
        return True
    elif detected == wrong:
        print("❌ FAIL! Still detecting .venv\\Scripts!")
        return False
    elif detected and "venv" in detected.lower():
        print(f"❌ FAIL! Detected path contains venv: {detected}")
        return False
    elif detected:
        print(f"⚠️  Detected different path: {detected}")
        print(f"   Expected: {expected}")
        return False
    else:
        print("❌ No project directory detected!")
        return False


async def main():
    print()
    print("🚀 Testing fix with ACTUAL CBOR scenario...")
    print()
    
    result = await test_actual_cbor_scenario()
    
    print()
    print("=" * 80)
    if result:
        print("🎉 FIX VERIFIED!")
        print("🎉 The project root detection works correctly!")
        return 0
    else:
        print("💥 FIX FAILED!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
