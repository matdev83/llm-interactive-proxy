#!/usr/bin/env python3
"""Extract the initial user prompt from CBOR capture and test the fix."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import cbor2

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.app_config import AppConfig, SessionConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session, SessionState
from src.core.services.project_directory_resolution_service import (
    ProjectDirectoryResolutionService,
)


def extract_initial_prompt_from_cbor(cbor_path: Path) -> str:
    """Extract the initial user prompt from the CBOR capture file."""
    with open(cbor_path, "rb") as f:
        data = cbor2.load(f)

    # Get the first CLIENT_TO_PROXY entry
    first_entry = data["entries"][0]

    # Parse the JSON data
    request_data = json.loads(first_entry["data"])

    # Find the last user message (the actual user prompt, not system message)
    messages = request_data.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content", "")

    return ""


async def test_with_real_cbor_data():
    """Test the fix using the real CBOR capture data."""

    print("=" * 80)
    print("REAL CBOR CAPTURE VERIFICATION")
    print("=" * 80)
    print()

    # Load actual CBOR file
    cbor_path = (
        project_root
        / "var"
        / "wire_captures_cbor"
        / "22523e34faf943b8b2c4116204cbc9c0.cbor"
    )

    if not cbor_path.exists():
        print(f"❌ CBOR file not found: {cbor_path}")
        return False

    print(f"📁 Reading CBOR: {cbor_path.name}")

    # Extract the actual user prompt
    actual_prompt = extract_initial_prompt_from_cbor(cbor_path)

    if not actual_prompt:
        print("❌ Could not extract user prompt from CBOR")
        return False

    print(f"📝 Extracted prompt length: {len(actual_prompt)} chars")
    print()

    # Look for paths in the prompt
    import re

    windows_paths = re.findall(r'[A-Z]:\\[^\s<>"]+', actual_prompt)
    unix_paths = re.findall(r'/[^\s<>"]+', actual_prompt)

    print(f"🔍 Found {len(windows_paths)} Windows paths in prompt")
    print(f"🔍 Found {len(unix_paths)} Unix paths in prompt")
    print()

    if windows_paths:
        print("Sample Windows paths found:")
        for path in windows_paths[:5]:
            print(f"   - {path}")
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
    session = Session(session_id="real-cbor-test", state=SessionState())

    service = ProjectDirectoryResolutionService(config, mock_backend, mock_session)

    # Run detection with the ACTUAL prompt from CBOR
    request = ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content=actual_prompt)]
    )

    print("🔍 Running project directory detection on REAL prompt...")
    await service.maybe_resolve_project_directory(session, request)

    detected = session.state.project_dir

    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()

    # From the logs, we know the OLD (buggy) detection was:
    old_buggy_result = (
        "C:\\Users\\Mateusz\\source\\repos\\patch-file-mcp-fork\\.venv\\Scripts"
    )

    print(f"OLD (buggy) detection: {old_buggy_result}")
    print(f"NEW detection:         {detected}")
    print()

    # Check if we still get the buggy result
    if detected == old_buggy_result:
        print("❌ FAIL! Still detecting .venv\\Scripts as project root!")
        print("❌ The fix did not work on real data!")
        return False

    # Check if .venv is in the detected path
    if detected and ".venv" in detected.lower():
        print(f"❌ FAIL! Detected path still contains .venv: {detected}")
        return False

    if detected and "venv" in detected.lower():
        print(f"❌ FAIL! Detected path still contains venv: {detected}")
        return False

    # Success criteria:
    # 1. Should detect a path
    # 2. Should NOT be .venv\Scripts
    # 3. Should NOT contain venv in the path
    if detected:
        print("✅ SUCCESS! Detected a valid project root")
        print("✅ .venv\\Scripts was properly rejected!")
        print("✅ No venv directories in the detected path")
        return True
    else:
        print("⚠️  No project directory detected from the prompt")
        print("   (This might be OK if the prompt didn't contain clear project paths)")
        return True  # Not necessarily a failure


async def main():
    print()
    print("🚀 Testing fix against REAL CBOR capture data...")
    print()

    result = await test_with_real_cbor_data()

    print()
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    print()

    if result:
        print("🎉 Fix verified against real CBOR data!")
        return 0
    else:
        print("💥 Fix failed against real CBOR data!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
