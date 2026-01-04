"""
Test script to verify the fix for _session_aliases memory leak.

The fix should:
1. Initialize _session_aliases in __init__
2. Clean up expired entries based on TTL
3. Enforce max_session_aliases limit
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_reactor_service import ToolCallReactorService


async def test_session_aliases_fix():
    """Test that _session_aliases is properly initialized and cleaned up."""
    # Create reactor with short TTL for testing
    reactor = ToolCallReactorService(
        session_alias_ttl_seconds=1,  # 1 second TTL for testing
        max_session_aliases=100,  # Small limit for testing
    )

    # Verify _session_aliases is initialized
    assert hasattr(
        reactor, "_session_aliases"
    ), "_session_aliases should be initialized"
    assert hasattr(
        reactor, "_session_aliases_last_access"
    ), "_session_aliases_last_access should be initialized"
    print("[PASS] _session_aliases is properly initialized")

    # Test that it works without AttributeError
    context = ToolCallContext(
        session_id="test_session_123",
        backend_name="test_backend",
        model_name="test_model",
        full_response=None,
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
        calling_agent="test_agent",
        timestamp=datetime.now(timezone.utc),
    )

    try:
        await reactor.process_tool_call(context)
        print("[PASS] No AttributeError when processing tool call")
    except AttributeError as e:
        print(f"[FAIL] AttributeError raised: {e}")
        return False

    # Verify entry was created
    assert "test_session_123" in reactor._session_aliases
    assert "test_session_123" in reactor._session_aliases_last_access
    print("[PASS] Session alias entry created correctly")

    # Test max_session_aliases limit
    print("\nTesting max_session_aliases limit...")
    for i in range(150):  # More than the limit of 100
        context = ToolCallContext(
            session_id=f"session_{i}",
            backend_name="test_backend",
            model_name="test_model",
            full_response=None,
            tool_name="test_tool",
            tool_arguments={"arg": f"value_{i}"},
            calling_agent="test_agent",
            timestamp=datetime.now(timezone.utc),
        )
        await reactor.process_tool_call(context)

    # Check that size is limited
    size = len(reactor._session_aliases)
    print(f"  After creating 150 sessions, _session_aliases size: {size}")
    assert size <= 100, f"Size should be <= 100, got {size}"
    print(f"[PASS] Max session aliases limit enforced (size: {size})")

    # Test TTL cleanup
    print("\nTesting TTL cleanup...")
    # Create an entry
    context = ToolCallContext(
        session_id="old_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response=None,
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
        calling_agent="test_agent",
        timestamp=datetime.now(timezone.utc),
    )
    await reactor.process_tool_call(context)
    assert "old_session" in reactor._session_aliases

    # Manually set last_access to be old
    reactor._session_aliases_last_access["old_session"] = datetime.now(
        timezone.utc
    ) - timedelta(seconds=2)

    # Process another call to trigger cleanup
    context2 = ToolCallContext(
        session_id="new_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response=None,
        tool_name="test_tool",
        tool_arguments={"arg": "value"},
        calling_agent="test_agent",
        timestamp=datetime.now(timezone.utc),
    )
    await reactor.process_tool_call(context2)

    # Old session should be cleaned up
    assert (
        "old_session" not in reactor._session_aliases
    ), "Old session should be cleaned up"
    assert "new_session" in reactor._session_aliases, "New session should still exist"
    print("[PASS] TTL-based cleanup works correctly")

    print("\n[SUCCESS] All tests passed! Memory leak fix is working.")
    return True


if __name__ == "__main__":
    success = asyncio.run(test_session_aliases_fix())
    sys.exit(0 if success else 1)
