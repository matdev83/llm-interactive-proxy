"""Test WireCapture race condition fix - simple test.

This test verifies that WireCapture has thread protection for cache variables.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import threading
from src.core.services.wire_capture_service import WireCapture


def test_wire_capture_thread_safety():
    """Verify WireCapture has thread lock for cache protection."""
    # Create instance using __new__ to bypass pydantic validation
    capture = WireCapture.__new__(WireCapture)
    
    # Verify thread lock exists
    assert hasattr(capture, '_thread_lock'), "WireCapture must have _thread_lock attribute"
    
    # Verify _cache_lock exists
    assert hasattr(capture, '_cache_lock'), "WireCapture must have _cache_lock attribute"
    
    print(f"PASSED: WireCapture has locks for cache protection")
    print(f"  _thread_lock: {type(capture._thread_lock).__name__}")
    print(f"  _cache_lock: {type(capture._cache_lock).__name__}")


if __name__ == "__main__":
    test_wire_capture_thread_safety()
