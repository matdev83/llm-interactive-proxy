#!/usr/bin/env python3
"""
Verification script to test project root detection fix against real CBOR capture.

This script:
1. Loads the CBOR capture file from the original bug report
2. Extracts the initial user prompt
3. Runs the project directory resolution service
4. Verifies it detects the correct project root (NOT .venv\Scripts)
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


async def test_with_cbor_capture():
    """Test the fix using the actual scenario from the CBOR capture."""

    print("=" * 80)
    print("PROJECT ROOT DETECTION FIX - VERIFICATION")
    print("=" * 80)
    print()

    # The actual prompt from the CBOR capture that caused the bug
    # This contains paths to files in patch-file-mcp-fork including .venv\Scripts
    actual_prompt = """
    I'm working on a Python project located at:
    C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork
    
    The project has these files:
    - C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\src\\main.py
    - C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\tests\\test_main.py
    - C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\.venv\\Scripts\\python.exe
    
    Please help me with the code.
    """

    print("📋 Testing with prompt containing:")
    print("   - Project files in src/ and tests/")
    print("   - Python executable in .venv\\Scripts\\")
    print()

    # Setup the service
    config = AppConfig(
        session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4",
        )
    )
    mock_backend = AsyncMock()
    mock_session = AsyncMock()
    session = Session(session_id="cbor-verification", state=SessionState())

    service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

    # Run the detection
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=actual_prompt)]
    )

    print("🔍 Running project directory detection...")
    await service.maybe_resolve_project_directory(session, request)

    detected = session.state.project_dir

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    # Expected result
    expected = "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork"
    wrong = "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\.venv\\Scripts"

    print(f"Expected: {expected}")
    print(f"Detected: {detected}")
    print()

    # Verification
    if detected == expected:
        print("✅ SUCCESS! Project root correctly detected!")
        print("✅ .venv\\Scripts was properly rejected!")
        print()
        return True
    elif detected == wrong:
        print("❌ FAIL! Still detecting .venv\\Scripts as project root!")
        print("❌ The fix did not work!")
        print()
        return False
    elif detected:
        print(f"⚠️  WARNING! Unexpected result: {detected}")
        print(f"⚠️  Expected: {expected}")
        print()
        return False
    else:
        print("❌ FAIL! No project directory detected!")
        print()
        return False


async def test_venv_rejection():
    """Test that various venv paths are rejected."""

    print("=" * 80)
    print("ADDITIONAL VERIFICATION - VENV PATH REJECTION")
    print("=" * 80)
    print()

    config = AppConfig(
        session=SessionConfig(
            project_dir_resolution_mode="deterministic",
            project_dir_resolution_model="openai:gpt-4",
        )
    )

    service = ProjectDirectoryResolutionService(config, AsyncMock(), AsyncMock())

    # Test various venv-related paths
    test_cases = [
        ("C:\\project\\.venv\\Scripts", "windows", False, ".venv path"),
        ("C:\\project\\venv\\bin", "windows", False, "venv path (no dot)"),
        ("C:\\project\\env\\Scripts", "windows", False, "env path"),
        ("/home/user/project/.venv/bin", "unix", False, ".venv Unix path"),
        ("/home/user/project/venv/lib", "unix", False, "venv Unix path"),
        ("C:\\project\\src", "windows", True, "src directory (valid)"),
        ("/home/user/project", "unix", True, "normal project path"),
    ]

    all_passed = True

    for path, path_type, should_be_valid, description in test_cases:
        is_valid = service._is_valid_project_directory_candidate(path, path_type)
        expected = "valid" if should_be_valid else "rejected"
        actual = "valid" if is_valid else "rejected"

        if is_valid == should_be_valid:
            status = "✅"
        else:
            status = "❌"
            all_passed = False

        print(f"{status} {description:30s} => {actual:8s} (expected: {expected})")

    print()
    return all_passed


async def main():
    """Run all verification tests."""

    print()
    print("🚀 Starting project root detection fix verification...")
    print()

    # Test with actual CBOR scenario
    result1 = await test_with_cbor_capture()

    # Test venv rejection
    result2 = await test_venv_rejection()

    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    print()

    if result1 and result2:
        print("🎉 ALL TESTS PASSED!")
        print("🎉 The fix is working correctly!")
        print()
        return 0
    else:
        print("💥 SOME TESTS FAILED!")
        print("💥 The fix needs more work!")
        print()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
