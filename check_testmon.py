import os
import subprocess
import sys

# Check current directory
print(f"Current directory: {os.getcwd()}")
print(f"Testmon env var: {os.environ.get('TESTMON_DATAFILE')}")

# Clean up existing testmon file
testmon_file = ".pytest_cache/.testmondata"
if os.path.exists(testmon_file):
    os.remove(testmon_file)
    print("[CLEAN] Removed existing testmon file")

# First run - should collect testmon data (no selection = full test suite)
# Use a very small subset to make it fast
print("\n" + "=" * 60)
print("First run - simulate full test suite (no specific path)")
print("=" * 60)
env = os.environ.copy()
env["DEBUG_TESTMON"] = "1"
result = subprocess.run(
    [sys.executable, "-m", "pytest", "-n", "0", "-v", "-k", "test_pyproject_toml_exists"],
    cwd=os.getcwd(),
    capture_output=True,
    text=True,
    env=env
)
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
print(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)

# Check if testmon file exists
if os.path.exists(testmon_file):
    print(f"\n[OK] Testmon data file exists: {testmon_file}")
    print(f"  File size: {os.path.getsize(testmon_file)} bytes")
else:
    print(f"\n[MISSING] Testmon data file NOT found: {testmon_file}")
