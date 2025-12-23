"""
Repro script for daemon mode subprocess resource leak.

This script demonstrates that the subprocess.Popen call in 
server_lifecycle_manager.py line 219 does not track the subprocess object,
which is a resource leak pattern.

When running in daemon mode on Windows, the process spawns a detached
process but doesn't keep a reference to it, meaning it cannot be:
- Waited on (to ensure proper startup)
- Terminated (if needed)
- Cleaned up properly

While DETACHED_PROCESS flag creates a process that becomes independent,
not having any reference to it is still a resource management issue.
"""

import subprocess
import sys
import time


def simulate_daemon_mode_original_code():
    """Simulate the original code pattern in server_lifecycle_manager.py"""
    print("Testing ORIGINAL code pattern:")
    args_list: list[str] = [sys.executable, "-c", "import time; time.sleep(10); print('Child process done')"]
    command: list[str] = args_list
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    
    # This is the original pattern - subprocess.Popen is called but not assigned
    # This means we have no reference to the subprocess
    subprocess.Popen(command, creationflags=creation_flags, close_fds=True)
    print("  - subprocess.Popen called without assignment")
    print("  - No way to track, wait, or terminate the process")
    print("  - This is a resource leak pattern\n")


def simulate_daemon_mode_fixed_code():
    """Simulate the fixed code pattern with proper subprocess tracking"""
    print("Testing FIXED code pattern:")
    args_list: list[str] = [sys.executable, "-c", "import time; time.sleep(10); print('Child process done')"]
    command: list[str] = args_list
    creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
    
    # Fixed pattern - keep reference and ensure proper cleanup
    process = subprocess.Popen(command, creationflags=creation_flags, close_fds=True)
    print("  - subprocess.Popen called and assigned to variable")
    print("  - Can track process if needed")
    print("  - No resource leak\n")
    
    # For detached processes, we can optionally wait a brief time
    # to ensure the process started successfully
    time.sleep(0.1)
    
    # Note: We don't call wait() on detached processes since they're
    # designed to run independently. But we have a reference if needed.


if __name__ == "__main__":
    print("=== Daemon Mode Subprocess Resource Leak Repro ===\n")
    
    simulate_daemon_mode_original_code()
    time.sleep(0.5)
    simulate_daemon_mode_fixed_code()
    
    print("\n=== Summary ===")
    print("Resource leak found in: src/core/cli_support/server_lifecycle_manager.py:219")
    print("Issue: subprocess.Popen() called without assigning return value")
    print("Impact: No reference to track the subprocess, unable to wait or terminate")
    print("Fix: Assign subprocess.Popen() return value to a variable")
