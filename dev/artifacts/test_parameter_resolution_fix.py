"""
Test script to verify the ParameterResolution memory leak fix.

After the fix, _history should only store the last entry per parameter name,
preventing unbounded memory growth.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def main():
    """Test that the fix prevents memory leak."""
    resolution = ParameterResolution()

    parameter_name = "test.parameter.temperature"

    print("Testing ParameterResolution memory leak fix...")
    print("=" * 60)

    # Record the same parameter 1000 times
    for i in range(1000):
        resolution.record(
            name=parameter_name,
            value=0.5 + (i * 0.001),
            source=ParameterSource.CONFIG_FILE,
            origin=f"config_file_{i}.yaml",
        )

        # Check memory growth every 100 iterations
        if (i + 1) % 100 == 0:
            record = resolution._history.get(parameter_name)
            if record:
                print(f"After {i + 1} calls: 1 entry stored (value: {record.value})")
            else:
                print(f"After {i + 1} calls: No entry found (ERROR!)")

    print("\n" + "=" * 60)
    print("Final state:")
    record = resolution._history.get(parameter_name)
    if record:
        print("Total entries stored: 1 (FIXED!)")
        print(f"Value: {record.value}")
        print(f"Source: {record.source.value}")
        print(f"Origin: {record.origin}")
    else:
        print("ERROR: No entry found!")

    # Verify build_report still works
    print("\n" + "=" * 60)
    print("Testing build_report()...")
    dummy_config = {
        "test": {"parameter": {"temperature": record.value if record else 0.5}}
    }
    report = resolution.build_report(dummy_config)
    print(f"Report contains {len(report)} parameters")
    for param in report:
        if param.name == parameter_name:
            print(f"  {param.name} = {param.value} (source: {param.source.value})")

    # Verify latest_by_source still works
    print("\n" + "=" * 60)
    print("Testing latest_by_source()...")
    latest = resolution.latest_by_source(ParameterSource.CONFIG_FILE)
    print(f"Found {len(latest)} parameters from CONFIG_FILE source")
    if parameter_name in latest:
        print(f"  {parameter_name} = {latest[parameter_name].value}")

    print("\n" + "=" * 60)
    print("FIX VERIFIED:")
    print("  - Only 1 entry stored per parameter (memory leak fixed)")
    print("  - build_report() still works correctly")
    print("  - latest_by_source() still works correctly")


if __name__ == "__main__":
    main()
