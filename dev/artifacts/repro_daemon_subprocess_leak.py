"""
Reproduction script for subprocess resource leak in server_lifecycle_manager.py.

VULNERABLE FILE: src/core/cli_support/server_lifecycle_manager.py
VULNERABLE LINES: 214-230 in _run_daemon_windows()

LEAK SCENARIO:
On Windows, when starting the daemon process:
1. Line 214-221: Build command and create subprocess.Popen()
   - daemon_process = subprocess.Popen(...)
2. Line 223-225: Check if daemon started successfully
   - if daemon_process.poll() is not None: raise SystemExit(1)
3. Line 227-228: time.sleep(2), then sys.exit(0)

THE LEAK:
- If an exception occurs AFTER subprocess.Popen() but BEFORE the poll() check,
  the daemon_process reference is lost and cleanup is never called.
- With close_fds=True, file descriptors are closed, but the subprocess
  object itself may hold resources that won't be properly cleaned.
- If Popen succeeds but poll() raises an unexpected exception,
  the subprocess continues running but we have no handle to it.

ATTACK VECTOR:
A remote attacker can repeatedly trigger exception paths during subprocess
initialization (e.g., by causing resource exhaustion, network issues,
or by sending malformed requests that cause validation to fail unpredictably).
Each failed attempt leaks a subprocess object and potentially a running process.
"""

import subprocess
import sys
import time


def demo_vulnerable_code():
    """
    Demonstrate the vulnerable pattern from server_lifecycle_manager.py:214-230.
    """
    print("=" * 70)
    print("VULNERABLE VERSION: from server_lifecycle_manager.py")
    print("=" * 70)

    # Simulate the vulnerable code pattern
    daemon_process = None
    try:
        print("[VULN] Building command...")
        command = [
            sys.executable,
            "-c",
            "import time; time.sleep(100); print('daemon')",
        ]

        print("[VULN] Creating subprocess...")
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        daemon_process = subprocess.Popen(
            command, creationflags=creation_flags, close_fds=True
        )
        print(f"[VULN] Process created with PID {daemon_process.pid}")

        # SIMULATED BUG: Exception occurs between Popen and poll check
        # This could be any unexpected exception
        print("[VULN] Simulating unexpected exception before poll()...")
        raise RuntimeError("Simulated unexpected error during daemon startup")

        # This code never executes due to the exception above
        print("[VULN] Checking if process started...")
        if daemon_process.poll() is not None:
            print("[VULN] Process failed to start")
            raise SystemExit(1)

        print("[VULN] Sleeping 2 seconds...")
        time.sleep(2)
        print("[VULN] Exiting parent...")
        sys.exit(0)

    except Exception as e:
        print(f"[VULN] Exception caught: {e}")
        print(f"[VULN] daemon_process is None: {daemon_process is None}")

        # BUG: No cleanup of daemon_process here!
        # The subprocess reference is leaked
        if daemon_process is None:
            print("[VULN] No process to clean up")
        else:
            print(f"[VULN] Process {daemon_process.pid} not cleaned up - LEAK!")

        return daemon_process


def demo_fixed_code():
    """
    Demonstrate the fixed pattern with proper cleanup.
    """
    print("\n" + "=" * 70)
    print("FIXED VERSION: with proper exception handling")
    print("=" * 70)

    daemon_process = None
    try:
        print("[FIXED] Building command...")
        command = [
            sys.executable,
            "-c",
            "import time; time.sleep(100); print('daemon')",
        ]

        print("[FIXED] Creating subprocess...")
        creation_flags = getattr(subprocess, "DETACHED_PROCESS", 0)
        daemon_process = subprocess.Popen(
            command, creationflags=creation_flags, close_fds=True
        )
        print(f"[FIXED] Process created with PID {daemon_process.pid}")

        # SIMULATED BUG: Exception occurs between Popen and poll check
        print("[FIXED] Simulating unexpected exception before poll()...")
        raise RuntimeError("Simulated unexpected error during daemon startup")

        # This code never executes due to the exception above
        if daemon_process.poll() is not None:
            print("[FIXED] Process failed to start")
            raise SystemExit(1)

        print("[FIXED] Sleeping 2 seconds...")
        time.sleep(2)
        print("[FIXED] Exiting parent...")
        sys.exit(0)

    except Exception as e:
        print(f"[FIXED] Exception caught: {e}")
        print(f"[FIXED] daemon_process is None: {daemon_process is None}")

        # FIX: Always clean up the subprocess
        if daemon_process is not None:
            print(f"[FIXED] Cleaning up process {daemon_process.pid}...")
            try:
                # For daemon processes, we should terminate them on failure
                if daemon_process.poll() is None:
                    daemon_process.terminate()
                    try:
                        daemon_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        daemon_process.kill()
                        daemon_process.wait(timeout=5)
                    print("[FIXED] Process terminated and cleaned up")
            except Exception as cleanup_error:
                print(f"[FIXED] Error during cleanup: {cleanup_error}")
        else:
            print("[FIXED] No process to clean up")

        # Re-raise the exception after cleanup
        raise


def check_running_processes():
    """Check for leaked python.exe processes."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split("\n")
        # Subtract header
        python_count = max(0, len(lines) - 1)
        print(f"\n[LEAK CHECK] Found {python_count} python.exe processes")
    except Exception as e:
        print(f"[LEAK CHECK] Could not check processes: {e}")


def main():
    """Run the demonstration."""
    check_running_processes()

    print("\n--- TEST 1: VULNERABLE VERSION ---\n")
    try:
        leaked = demo_vulnerable_code()
    except Exception:
        pass

    check_running_processes()

    print("\n" + "=" * 70)
    print("MANUAL VERIFICATION REQUIRED")
    print("=" * 70)
    print("Please check Task Manager for python.exe processes.")
    print("If vulnerable version leaked, you'll see a 'sleep(100)' process running.")
    print("=" * 70)


if __name__ == "__main__":
    main()
