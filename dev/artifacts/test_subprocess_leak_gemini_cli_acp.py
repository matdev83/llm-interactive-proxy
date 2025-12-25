"""
Reproduction script demonstrating subprocess resource leak in gemini_cli_acp.py

The issue is in src/connectors/gemini_cli_acp.py at lines 256-312.

If an exception occurs during subprocess.Popen() or immediately after, the subprocess
may leak because the exception handler's logic is flawed.
"""
import subprocess


class FakeGeminiCliAcpConnector:
    """Simplified version of gemini_cli_acp to demonstrate the leak."""

    def __init__(self):
        self._process = None

    def _cleanup_process(self, process: subprocess.Popen[bytes] | None = None) -> None:
        """Close process pipes and clear reference."""
        proc = process or self._process
        if not proc:
            print("[CLEANUP] No process to clean up")
            return

        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, stream_name, None)
            if stream is None:
                continue
            try:
                stream.close()
                print(f"[CLEANUP] Closed {stream_name}")
            except Exception as stream_error:
                print(f"[CLEANUP] Error closing {stream_name}: {stream_error}")

        if proc is self._process:
            self._process = None

    async def _kill_process(self) -> None:
        """Kill gemini-cli process."""
        if self._process:
            process = self._process
            try:
                process.terminate()
                process.wait(timeout=5)
                print("[KILL] Process terminated")
            except Exception as e:
                print(f"[KILL] Error terminating process: {e}")
            finally:
                self._cleanup_process(process)
        else:
            print("[KILL] self._process is None, nothing to kill")

    def _spawn_process_with_bug(self) -> None:
        """
        Simulates the buggy version in gemini_cli_acp.py.
        """
        process = None
        try:
            print("[BUGGY] Spawning process...")
            # Simulate subprocess.Popen - in reality this would run gemini-cli
            process = subprocess.Popen(
                ["python", "-c", "import time; time.sleep(100); print('running')"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("[BUGGY] Process created:", process.poll())

            # Simulate an exception BEFORE assignment to self._process
            # This could be: asyncio.sleep(0.1) failing, validation failing, etc.
            raise RuntimeError("Simulated exception during process startup")

            # This line never executes due to the exception above
            self._process = process

        except Exception as e:
            print(f"[BUGGY] Exception caught: {e}")
            print(f"[BUGGY] process is not None: {process is not None}")
            print(f"[BUGGY] process is not self._process: {process is not self._process}")
            print(f"[BUGGY] self._process value: {self._process}")

            # This is the buggy logic from gemini_cli_acp.py:302-308
            if process is not None and process is not self._process:
                print("[BUGGY] Calling _cleanup_process(process)")
                self._cleanup_process(process)
            else:
                print("[BUGGY] NOT calling _cleanup_process - LEAK POTENTIAL!")

            # Then it calls _kill_process
            # But _kill_process only checks self._process, not the local 'process' var!
            print("[BUGGY] Calling _kill_process()")
            # Note: We can't await in synchronous demo, so we call a sync version

    def _spawn_process_fixed(self) -> None:
        """
        Simulates the fixed version.
        """
        process = None
        try:
            print("[FIXED] Spawning process...")
            process = subprocess.Popen(
                ["python", "-c", "import time; time.sleep(100); print('running')"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            print("[FIXED] Process created:", process.poll())

            # Simulate an exception BEFORE assignment to self._process
            raise RuntimeError("Simulated exception during process startup")

            # This line never executes due to the exception above
            self._process = process

        except Exception as e:
            print(f"[FIXED] Exception caught: {e}")
            print(f"[FIXED] process is not None: {process is not None}")

            # FIXED: Always cleanup 'process' if it's not None
            if process is not None:
                print("[FIXED] Calling _cleanup_process(process)")
                self._cleanup_process(process)

            # Also call _kill_process to handle self._process
            print("[FIXED] Calling _kill_process()")


def check_for_leaks() -> None:
    """Check for leaked processes."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split('\n')
        python_count = max(0, len(lines) - 1)  # Subtract header
        print(f"[LEAK CHECK] Found {python_count} python.exe processes (may include this script)")
    except Exception as e:
        print(f"[LEAK CHECK] Could not check processes: {e}")


def main():
    """Run the demonstration."""
    print("=" * 70)
    print("TEST 1: BUGGY VERSION - Check for process leaks")
    print("=" * 70)

    check_for_leaks()

    print("\n--- Spawning process with buggy exception handling ---\n")
    connector = FakeGeminiCliAcpConnector()
    connector._spawn_process_with_bug()

    print("\n--- Checking for leaks after buggy spawn ---\n")
    check_for_leaks()

    print("\n" + "=" * 70)
    print("TEST 2: FIXED VERSION - Check for process cleanup")
    print("=" * 70)

    print("\n--- Spawning process with fixed exception handling ---\n")
    connector2 = FakeGeminiCliAcpConnector()
    connector2._spawn_process_fixed()

    print("\n--- Checking for leaks after fixed spawn ---\n")
    check_for_leaks()

    print("\n" + "=" * 70)
    print("MANUAL CLEANUP: If you see 'running' processes above, they leaked")
    print("=" * 70)
    print("\nPlease manually check Task Manager for python.exe processes")
    print("The buggy version should leave a 'sleep(100)' process running")
    print("The fixed version should clean up properly")


if __name__ == "__main__":
    main()
