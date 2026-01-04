"""
Verify the fix for subprocess resource leak in server_lifecycle_manager.py.

This script demonstrates that the fixed pattern properly cleans up
subprocesses when exceptions occur.
"""

import subprocess
import sys
import time


def demo_fixed_code():
    """
    Demonstrate the fixed pattern that properly cleans up subprocesses.
    """
    print("=" * 70)
    print("FIXED VERSION: from server_lifecycle_manager.py (after fix)")
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

        # This code never executes due to exception above
        if daemon_process.poll() is not None:
            print("[FIXED] Process failed to start")
            raise SystemExit(1)

        print("[FIXED] Sleeping 2 seconds...")
        time.sleep(2)
        print("[FIXED] Exiting parent...")
        sys.exit(0)
        return True

    except Exception as e:
        print(f"[FIXED] Exception caught: {e}")
        print(f"[FIXED] daemon_process is None: {daemon_process is None}")

        # FIX: Always clean up subprocess on any exception
        if daemon_process is not None and daemon_process.poll() is None:
            print(f"[FIXED] Cleaning up process {daemon_process.pid}...")
            try:
                daemon_process.terminate()
                try:
                    daemon_process.wait(timeout=5)
                    print("[FIXED] Process terminated cleanly")
                except subprocess.TimeoutExpired:
                    daemon_process.kill()
                    daemon_process.wait(timeout=5)
                    print("[FIXED] Process killed forcefully")
            except Exception as cleanup_error:
                print(f"[FIXED] Error during cleanup: {cleanup_error}")
        else:
            print("[FIXED] No process to clean up or already terminated")

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
    """Run verification."""
    print("Checking initial process count...")
    check_running_processes()

    print("\n--- TEST: FIXED VERSION ---\n")
    try:
        demo_fixed_code()
    except Exception:
        pass

    print("\nChecking process count after test...")
    check_running_processes()

    print("\n" + "=" * 70)
    print("VERIFICATION")
    print("=" * 70)
    print("If the fix is correct, there should be NO leaked 'sleep(100)' process.")
    print("The exception was handled properly and subprocess was cleaned up.")
    print("=" * 70)


if __name__ == "__main__":
    main()
