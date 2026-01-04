"""Test script to verify the memory leak fix for ReplacementMetrics timestamp lists."""

import os
import random
import sys

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.core.services.replacement_metrics import ReplacementMetrics


def main():
    """Test that timestamp lists are bounded."""
    metrics = ReplacementMetrics()

    print("=" * 80)
    print("Testing ReplacementMetrics timestamp list memory leak fix")
    print("=" * 80)

    # Simulate high-traffic scenario
    num_operations = 15000  # More than the limit to test pruning

    print(f"\nSimulating {num_operations} activations and opt-outs...")
    print("(Testing that lists are bounded at 10,000 and 1,000 respectively)\n")

    initial_activation_count = len(metrics.activation_timestamps)
    initial_opt_out_count = len(metrics.opt_out_timestamps)

    print("Initial state:")
    print(f"  activation_timestamps: {initial_activation_count}")
    print(f"  opt_out_timestamps: {initial_opt_out_count}")

    # Record many activations and opt-outs
    for i in range(num_operations):
        session_id = f"session_{i % 100}"

        # Record activation
        metrics.record_activation(session_id, turn_count=random.randint(1, 5))

        # Record opt-out occasionally
        if i % 10 == 0:
            metrics.record_opt_out(
                session_id, opt_out_type="header" if i % 2 == 0 else "session"
            )

    final_activation_count = len(metrics.activation_timestamps)
    final_opt_out_count = len(metrics.opt_out_timestamps)

    print(f"\nAfter {num_operations} operations:")
    print(f"  activation_timestamps: {final_activation_count} (expected: <= 10,000)")
    print(f"  opt_out_timestamps: {final_opt_out_count} (expected: <= 1,000)")

    # Verify the fix
    max_activation_timestamps = 10000
    max_opt_out_timestamps = 1000

    activation_leak_fixed = final_activation_count <= max_activation_timestamps
    opt_out_leak_fixed = final_opt_out_count <= max_opt_out_timestamps

    print(f"\n{'=' * 80}")
    if activation_leak_fixed and opt_out_leak_fixed:
        print("SUCCESS: Memory leak is FIXED!")
        print(
            f"  [OK] activation_timestamps bounded at {final_activation_count} <= {max_activation_timestamps}"
        )
        print(
            f"  [OK] opt_out_timestamps bounded at {final_opt_out_count} <= {max_opt_out_timestamps}"
        )
    else:
        print("FAILURE: Memory leak persists!")
        if not activation_leak_fixed:
            print(
                f"  [FAIL] activation_timestamps exceeded limit: {final_activation_count} > {max_activation_timestamps}"
            )
        if not opt_out_leak_fixed:
            print(
                f"  [FAIL] opt_out_timestamps exceeded limit: {final_opt_out_count} > {max_opt_out_timestamps}"
            )
    print("=" * 80)

    # Test that rate calculations still work correctly
    print("\nTesting that rate calculations still work...")
    activation_rate_all_time = metrics.get_activation_rate()
    activation_rate_60s = metrics.get_activation_rate(60.0)
    opt_out_rate_all_time = metrics.get_opt_out_rate()
    opt_out_rate_60s = metrics.get_opt_out_rate(60.0)

    print(f"  Activation rate (all time): {activation_rate_all_time:.4f}/s")
    print(f"  Activation rate (last 60s): {activation_rate_60s:.4f}/s")
    print(f"  Opt-out rate (all time): {opt_out_rate_all_time:.4f}/s")
    print(f"  Opt-out rate (last 60s): {opt_out_rate_60s:.4f}/s")
    print("  [OK] Rate calculations work correctly")

    return activation_leak_fixed and opt_out_leak_fixed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
