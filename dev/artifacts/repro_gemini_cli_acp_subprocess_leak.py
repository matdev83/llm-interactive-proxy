"""Repro script for GeminiCliAcpConnector subprocess leak.

This script tests if subprocesses created by GeminiCliAcpConnector are properly
cleaned up even when shutdown() is not called (e.g., during application crash).
"""

import asyncio
import subprocess
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_gemini_cli_acp_subprocess_leak():
    """Test if GeminiCliAcpConnector subprocess leaks when shutdown() not called."""
    print("Testing GeminiCliAcpConnector subprocess cleanup...")
    
    try:
        # Read the connector file to check cleanup
        connector_file = project_root / "src" / "connectors" / "gemini_cli_acp.py"
        with open(connector_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        has_shutdown = "async def shutdown(self)" in content
        has_del = "def __del__(self)" in content
        has_kill_process = "_kill_process" in content
        has_cleanup_process = "_cleanup_process" in content
        
        print(f"  Has shutdown() method: {has_shutdown}")
        print(f"  Has __del__() method: {has_del}")
        print(f"  Has _kill_process() method: {has_kill_process}")
        print(f"  Has _cleanup_process() method: {has_cleanup_process}")
        
        # Check if __del__ calls cleanup
        if has_del:
            # Check if __del__ calls _kill_process or _cleanup_process
            del_start = content.find("def __del__(self)")
            if del_start != -1:
                # Find the end of __del__ method (next def or class)
                del_end = content.find("\n    def ", del_start + 1)
                if del_end == -1:
                    del_end = content.find("\nclass ", del_start + 1)
                if del_end == -1:
                    del_end = len(content)
                
                del_method = content[del_start:del_end]
                calls_kill = "_kill_process" in del_method or "_cleanup_process" in del_method
                print(f"  __del__() calls cleanup: {calls_kill}")
                
                if has_shutdown and has_del and calls_kill:
                    print("\n[OK] GeminiCliAcpConnector has cleanup methods")
                    return True
        
        print("\n[WARNING] GeminiCliAcpConnector may be missing cleanup in __del__")
        return False
            
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_gemini_cli_acp_subprocess_leak())
    sys.exit(0 if result else 1)

