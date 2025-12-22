"""
Repro script to demonstrate memory leak in ParameterResolution._history.

The ParameterResolution.record() method appends to a list every time it's called
for the same parameter name, but build_report() only uses the last entry (record[-1]).
This means all previous entries accumulate in memory without any cleanup.

This script demonstrates unbounded growth of the _history dictionary.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def main():
    """Demonstrate the memory leak."""
    resolution = ParameterResolution()

    # Simulate repeated calls to record() for the same parameter
    # This could happen if config is reloaded or if multiple sources override
    # the same parameter multiple times
    parameter_name = "test.parameter.temperature"

    print("Recording parameter values repeatedly...")
    print("=" * 60)

    # Record the same parameter 1000 times (simulating config reloads or overrides)
    for i in range(1000):
        resolution.record(
            name=parameter_name,
            value=0.5 + (i * 0.001),  # Slightly different values
            source=ParameterSource.CONFIG_FILE,
            origin=f"config_file_{i}.yaml",
        )

        # Check memory growth every 100 iterations
        if (i + 1) % 100 == 0:
            entries = resolution._history.get(parameter_name, [])
            print(f"After {i + 1} calls: {len(entries)} entries stored in _history")
            print(f"  Memory usage: ~{len(entries) * 200} bytes (estimated)")

    print("\n" + "=" * 60)
    print("Final state:")
    entries = resolution._history.get(parameter_name, [])
    print(f"Total entries stored: {len(entries)}")
    print(f"Only the last entry is used by build_report(): {entries[-1].value}")

    # Show that build_report only uses the last entry
    print("\n" + "=" * 60)
    print("Calling build_report() - it only uses record[-1]:")
    # Create a dummy config dict
    dummy_config = {"test": {"parameter": {"temperature": entries[-1].value}}}
    report = resolution.build_report(dummy_config)
    print(f"Report contains {len(report)} parameters")
    for param in report:
        if param.name == parameter_name:
            print(f"  {param.name} = {param.value} (source: {param.source.value})")
            print(f"  But {len(entries)} entries are still stored in memory!")

    print("\n" + "=" * 60)
    print("MEMORY LEAK CONFIRMED:")
    print(f"  - {len(entries)} entries stored")
    print(f"  - Only 1 entry is actually used")
    print(f"  - {len(entries) - 1} entries are leaked memory")
    print(f"  - In a long-running server with config reloads, this grows unbounded")


if __name__ == "__main__":
    main()
