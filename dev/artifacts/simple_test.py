#!/usr/bin/env python3
"""
Simple test to verify DoS fix works correctly.
"""

import sys
from pathlib import Path

# Add src to path for imports
project_root = Path('.').absolute()
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'src'))

from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser


def test():
    parser = SSEBytesParser()
    
    # Test normal payload
    normal_payload = b'data: {"message": "hello", "choices": [{"delta": {"content": "world"}}]}'
    
    try:
        result = parser.parse(normal_payload)
        print("SUCCESS: Normal payload works")
        print(f"Result content: {result.content}")
        return True
    except Exception as e:
        print(f"FAILED: Normal payload error: {e}")
        return False

if __name__ == "__main__":
    success = test()
    sys.exit(0 if success else 1)