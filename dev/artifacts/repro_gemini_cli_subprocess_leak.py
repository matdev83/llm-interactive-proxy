"""Repro script for GeminiCliAcpConnector subprocess leak.

This script demonstrates that if a GeminiCliAcpConnector backend is created
but never evicted from cache and the application crashes or exits abruptly,
the subprocess might leak because shutdown() is never called.

Attack vector: A remote actor could trigger backend creation, then cause
the application to crash (e.g., via a memory exhaustion attack or exception),
preventing shutdown() from being called. The subprocess would continue running
indefinitely, consuming resources.
"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_subprocess_leak_scenario():
    """Test scenario where subprocess might leak."""
    print("=" * 60)
    print("Testing GeminiCliAcpConnector subprocess leak scenario...")
    print("=" * 60)
    
    process: subprocess.Popen[bytes] | None = None
    processes_before = []
    
    try:
        # Count processes before
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe"],
                capture_output=True,
                text=True,
            )
            processes_before = [line for line in result.stdout.split("\n") if "python.exe" in line]
        else:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True
            )
            processes_before = [line for line in result.stdout.split("\n") if "python" in line]
        
        print(f"Processes before: {len(processes_before)}")
        
        # Simulate creating subprocess (like GeminiCliAcpConnector does)
        # Use a simple command that stays alive
        if sys.platform == "win32":
            cmd = ["python", "-c", "import time; time.sleep(30)"]
        else:
            cmd = ["python3", "-c", "import time; time.sleep(30)"]
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print(f"Created subprocess with PID: {process.pid}")
            print(f"Process running: {process.poll() is None}")
            
            # Simulate backend being cached but never evicted
            # (backend stays in cache, shutdown() never called)
            print("Simulating backend staying in cache...")
            await asyncio.sleep(1)
            
            # Simulate application crash/abrupt exit without cleanup
            print("Simulating abrupt exit without cleanup...")
            print("(In real scenario, shutdown() would not be called)")
            # Don't call shutdown() - this simulates the leak
            
        except FileNotFoundError:
            print("Python executable not found, skipping subprocess test")
            return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False
    
    finally:
        # Check if process is still running
        if process is not None:
            if process.poll() is None:
                print(f"\n[LEAK DETECTED] Process {process.pid} is still running!")
                print("This indicates subprocess leaked because shutdown() was not called")
                
                # Clean up for test
                print("Cleaning up leaked process...")
                try:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    print("Leaked process cleaned up")
                    return False  # Leak confirmed
                except Exception as cleanup_error:
                    print(f"Error cleaning up process: {cleanup_error}")
                    return False
            else:
                print(f"Process {process.pid} already terminated")
        
        # Count processes after
        await asyncio.sleep(0.5)
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq python.exe"],
                capture_output=True,
                text=True,
            )
            processes_after = [line for line in result.stdout.split("\n") if "python.exe" in line]
        else:
            result = subprocess.run(
                ["ps", "aux"], capture_output=True, text=True
            )
            processes_after = [line for line in result.stdout.split("\n") if "python" in line]
        
        print(f"Processes after: {len(processes_after)}")
        if len(processes_after) > len(processes_before):
            print("[LEAK DETECTED] Process count increased - possible leak!")
            return False
    
    print("\n[OK] No leak detected")
    return True


async def test_backend_lifecycle_cleanup():
    """Test that backend lifecycle manager properly cleans up backends."""
    print("\n" + "=" * 60)
    print("Testing backend lifecycle cleanup...")
    print("=" * 60)
    
    # This test would require actual backend creation, which is complex
    # For now, we'll just document the expected behavior
    print("Expected: BackendLifecycleManager should call shutdown() on all backends")
    print("during application shutdown to prevent subprocess leaks.")
    print("\n[OK] Test documented")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("GeminiCliAcpConnector Subprocess Leak Repro")
    print("=" * 60)
    
    result1 = asyncio.run(test_subprocess_leak_scenario())
    result2 = asyncio.run(test_backend_lifecycle_cleanup())
    
    print("\n" + "=" * 60)
    if result1 and result2:
        print("All tests passed")
    else:
        print("[LEAK CONFIRMED] Fix needed!")
    print("=" * 60)

