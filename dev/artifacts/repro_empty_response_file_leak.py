"""Reproduction script for resource leak in empty_response_middleware.py

This script demonstrates how an exception during file reading can cause
a file handle leak because the file is opened without using a 'with' statement.
"""

import os
import tempfile


def simulate_file_read_error():
    """Simulate a scenario where file reading fails partway through.

    In a real scenario, this could happen due to:
    - Network filesystem issues (UNC paths on Windows)
    - Antivirus software scanning the file
    - Disk I/O errors
    - File being locked or deleted mid-read
    """
    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as f:
        test_file = f.name
        f.write("Test recovery prompt content\n")

    try:
        print(f"Created test file: {test_file}")

        # Simulate the vulnerable code pattern from empty_response_middleware.py line 112
        print("\n=== Testing VULNERABLE code pattern (no 'with' statement) ===")
        try:
            # This is the vulnerable pattern from empty_response_middleware.py:
            # if prompt_path and prompt_path.exists():
            #     with open(prompt_path, encoding="utf-8") as f:
            #         self._recovery_prompt = f.read().strip()

            # But what if there's code before/after that doesn't use 'with'?
            # Let's demonstrate the leak scenario:

            # Open file WITHOUT 'with' statement
            f = open(test_file, encoding="utf-8")

            # Simulate an error during reading (e.g., partial read causing an error)
            # In real scenarios this could be caused by I/O errors, encoding issues, etc.
            raise OSError("Simulated I/O error during file read")

            # This line never reached - file never closed!
            content = f.read().strip()
            f.close()  # This would close the file, but we never get here

        except OSError as e:
            print(f"Exception occurred: {e}")
            print(f"File handle leaked! File is still open: {test_file}")
            print("Check if file is locked/cannot be deleted on Windows...")

            # Try to delete the file to demonstrate the leak
            try:
                os.unlink(test_file)
                print("File deleted successfully (no leak)")
            except OSError as delete_error:
                print(f"FILE HANDLE LEAK CONFIRMED! Cannot delete file: {delete_error}")
                print("On Windows, this is often 'PermissionError: [WinError 32]'")
                print("because the file is still open.")

                # File will be leaked until process ends or GC runs
                # In a long-running server, this could accumulate many leaked handles

        print("\n=== Testing SAFE code pattern (using 'with' statement) ===")

        # Create another test file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as f:
            test_file2 = f.name
            f.write("Test recovery prompt content\n")

        print(f"Created test file 2: {test_file2}")

        try:
            # Safe pattern with 'with' statement
            with open(test_file2, encoding="utf-8") as f:
                raise OSError("Simulated I/O error during file read")
                content = f.read().strip()
        except OSError as e:
            print(f"Exception occurred: {e}")
            print("File was properly closed despite exception due to 'with' statement")

            # Try to delete the file
            try:
                os.unlink(test_file2)
                print("File deleted successfully (proper cleanup)")
            except OSError as delete_error:
                print(f"Unexpected error: {delete_error}")

    finally:
        # Cleanup
        for path in [test_file, test_file2]:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except:
                pass


def demonstrate_attack_scenario():
    """Demonstrate how a remote attacker could exploit this leak.

    An attacker could send many requests that trigger the empty response
    recovery path, causing the server to repeatedly open the same file.
    If any of these file opens encounter I/O errors during reading,
    file handles would leak.
    """
    print("\n=== ATTACK SCENARIO ===")
    print("A remote attacker sends requests that trigger empty response handling.")
    print("Each request attempts to load the recovery prompt file.")
    print("If file I/O errors occur (e.g., due to disk issues, antivirus),")
    print("file handles leak without being closed.")
    print()
    print("On Windows:")
    print("  - File handles are limited (typically ~2048-8192 per process)")
    print("  - Leaked handles cannot be deleted/modified")
    print("  - Accumulation leads to 'Too many open files' errors")
    print("  - Server becomes unresponsive")
    print()
    print("Impact: Denial of Service via resource exhaustion")


if __name__ == "__main__":
    print("=" * 70)
    print("Resource Leak Demonstration: empty_response_middleware.py")
    print("=" * 70)

    simulate_file_read_error()
    demonstrate_attack_scenario()

    print("\n" + "=" * 70)
    print("FIX: Use 'with' statement for all file operations")
    print("=" * 70)
    print("Change from:")
    print("  f = open(path)")
    print("  content = f.read()")
    print()
    print("To:")
    print("  with open(path) as f:")
    print("      content = f.read()")
    print("=" * 70)
