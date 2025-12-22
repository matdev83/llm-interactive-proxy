"""Repro script for ParameterResolution._history memory leak.

This script demonstrates that ParameterResolution._history can grow unbounded
when many unique parameter names are encountered.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def main():
    """Demonstrate unbounded growth of _history dict."""
    resolution = ParameterResolution()
    
    print("Testing ParameterResolution._history memory leak...")
    print(f"Initial size: {len(resolution._history)}")
    
    # Simulate many unique parameter names being recorded
    # This could happen if config is loaded multiple times with different keys
    # or if dynamic config parameters are created
    for i in range(100000):
        param_name = f"dynamic.param.{i}.nested.value"
        resolution.record(
            param_name,
            value=f"value_{i}",
            source=ParameterSource.DERIVED,
            origin=f"test_origin_{i}",
        )
        
        if i % 10000 == 0:
            print(f"After {i} records: {len(resolution._history)} entries")
    
    print(f"Final size: {len(resolution._history)}")
    print(f"Memory leak confirmed: dict grew to {len(resolution._history)} entries")
    print("No cleanup mechanism exists - entries accumulate indefinitely")


if __name__ == "__main__":
    main()
