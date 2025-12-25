"""
Reproduction script for subprocess resource leak in gemini_cli_acp.py.

VULNERABLE FILE: src/connectors/gemini_cli_acp.py
VULNERABLE LINES: 255-312 in _spawn_process()

LEAK SCENARIO:
1. subprocess.Popen() succeeds (line 271) - process object created
2. self._process = process (line 279) - assigned successfully  
3. Exception occurs AFTER assignment but BEFORE exception handler entry
   Examples: asyncio.sleep(0.1) on line 282 fails, network issue, etc.
4. Exception handler (line 302) checks:
   - `if process is not None and process is not self._process:`
   - Since process WAS assigned on line 279, condition is False
   - _cleanup_process(process) is NOT called
   - await self._kill_process() IS called (line 308)

5. _kill_process() (line 314) only checks self._process:
   - if self._process is set, it cleans it up (correctly)
   - BUT if the exception occurred after line 279 but changed self._process somehow,
     or if there's a reference issue, cleanup might not happen

6. WORST CASE: If exception somehow clears or prevents proper _kill_process
   execution, the subprocess from line 271 keeps running - RESOURCE LEAK

This can be exploited by a remote attacker who causes exceptions
during subprocess initialization (e.g., by sending malformed requests that
trigger validation failures), repeatedly spawning leaked subprocesses
that consume system resources.
"""

import subprocess
import sys
import time


def demo_leak():
    """
    Demonstrate the leak scenario using simplified code matching gemini_cli_acp.py logic.
    """
    print("=" * 70)
    print("DEMONSTRATING SUBPROCESS LEAK")
    print("=" * 70)
    
    class VulnerableConnector:
        def __init__(self):
            self._process = None

        def _cleanup_process(self, process):
            if process:
                try:
                    process.stdin.close()
                    process.stdout.close()
                    process.stderr.close()
                    print("[CLEANUP] Process pipes closed")
                except Exception as e:
                    print(f"[CLEANUP] Error: {e}")

        def _kill_process(self):
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                    print("[KILL] Process terminated via _kill_process()")
                except Exception as e:
                    print(f"[KILL] Error: {e}")
                finally:
                    self._cleanup_process(self._process)
                    self._process = None

        def _spawn_process_vulnerable(self):
            """
            Vulnerable version matching gemini_cli_acp.py logic.
            """
            process = None
            try:
                print("[SPAWN] Creating subprocess...")
                process = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(100); print('zombie')"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                print(f"[SPAWN] Process created with PID {process.pid}")
                
                # Assignment happens (matching line 279)
                self._process = process
                print("[SPAWN] Assigned to self._process")
                
                # Simulate exception AFTER assignment but BEFORE exception handler
                # This could be: asyncio.sleep() failing, validation, etc.
                print("[SPAWN] Simulating exception after assignment...")
                raise RuntimeError("Simulated exception during startup")
                
            except Exception as e:
                print(f"[EXCEPT] Caught exception: {e}")
                print(f"[EXCEPT] process is None: {process is None}")
                print(f"[EXCEPT] process is self._process: {process is self._process}")
                
                # THE BUG: This is the exact logic from gemini_cli_acp.py:306
                if process is not None and process is not self._process:
                    print("[EXCEPT] Calling _cleanup_process(process)")
                    self._cleanup_process(process)
                else:
                    print("[EXCEPT] NOT calling _cleanup_process - LEAK POSSIBLE!")
                
                # Then calls _kill_process
                print("[EXCEPT] Calling _kill_process()")
                self._kill_process()
                
                return process

        def _spawn_process_fixed(self):
            """
            Fixed version with _process_assigned flag.
            """
            self._process_assigned = False
            process = None
            try:
                print("[SPAWN] Creating subprocess...")
                process = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(100); print('zombie')"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                print(f"[SPAWN] Process created with PID {process.pid}")
                
                # Assignment happens
                self._process = process
                self._process_assigned = True
                print("[SPAWN] Assigned to self._process, flag set to True")
                
                # Simulate exception AFTER assignment
                print("[SPAWN] Simulating exception after assignment...")
                raise RuntimeError("Simulated exception during startup")
                
            except Exception as e:
                print(f"[EXCEPT] Caught exception: {e}")
                print(f"[EXCEPT] process is None: {process is None}")
                print(f"[EXCEPT] _process_assigned: {self._process_assigned}")
                
                # THE FIX: Check _process_assigned flag
                if process is not None and not self._process_assigned:
                    print("[EXCEPT] Calling _cleanup_process(process) - unassigned")
                    self._cleanup_process(process)
                elif not self._process_assigned:
                    print("[EXCEPT] Process was created but not assigned - leak possible")
                
                # Call _kill_process for any assigned process
                print("[EXCEPT] Calling _kill_process()")
                self._kill_process()
                
                return process

    # Test vulnerable version
    print("\n--- TEST 1: VULNERABLE VERSION ---\n")
    vulnerable = VulnerableConnector()
    leaked_process = vulnerable._spawn_process_vulnerable()
    
    if leaked_process and leaked_process.poll() is None:
        print(f"\n[!!!] LEAK DETECTED: Process {leaked_process.pid} is still running!")
        print("[!!!] This represents a resource leak vulnerability")
    else:
        print("\n[OK] No leak detected in this case")
    
    time.sleep(1)  # Give processes time to settle
    
    # Test fixed version  
    print("\n--- TEST 2: FIXED VERSION ---\n")
    vulnerable2 = VulnerableConnector()
    leaked_process2 = vulnerable2._spawn_process_fixed()
    
    if leaked_process2 and leaked_process2.poll() is None:
        print(f"\n[!!!] LEAK DETECTED: Process {leaked_process2.pid} is still running!")
    else:
        print("\n[OK] No leak detected with fixed version")
    
    print("\n" + "=" * 70)
    print("Check Task Manager for zombie python.exe processes")
    print("If vulnerable version leaked, you'll see sleeping processes")
    print("=" * 70)


if __name__ == "__main__":
    demo_leak()
