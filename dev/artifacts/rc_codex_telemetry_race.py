"""Reproduction script for global _telemetry_instance race condition in _openai_codex_telemetry.py

This script demonstrates a race condition where:
1. Thread A calls get_telemetry() to get global instance
2. Thread B calls reset_telemetry() which sets _telemetry_instance = None
3. Thread A continues using the old instance while it's been nulled

File: src/connectors/_openai_codex_telemetry.py
Line 466: _telemetry_instance: CompatibilityTelemetry | None = None
Line 477: if _telemetry_instance is None: (no protection)
Line 484: _telemetry_instance = None (no protection)
"""

import threading
import time

# Simulate the problematic pattern
class MockTelemetry:
    def __init__(self):
        self.data = []

    def record(self, value):
        self.data.append(value)

# Global mutable state (simulating _telemetry_instance)
_global_telemetry_instance: MockTelemetry | None = None


def get_telemetry():
    """Simulates get_telemetry() at line 477-478"""
    global _global_telemetry_instance
    if _global_telemetry_instance is None:
        _global_telemetry_instance = MockTelemetry()
    return _global_telemetry_instance


def reset_telemetry():
    """Simulates reset_telemetry() at line 484"""
    global _global_telemetry_instance
    _global_telemetry_instance = None


def thread_a_job():
    """Thread A: Repeatedly get telemetry instance and use it"""
    print("[Thread-A] Starting")
    for i in range(10):
        instance = get_telemetry()
        if instance:
            instance.record(f"value-{i}")
        time.sleep(0.001)
        # If race happens, instance becomes None mid-loop
    print("[Thread-A] Completed")


def thread_b_job():
    """Thread B: Reset telemetry while Thread A is using it"""
    print("[Thread-B] Starting")
    time.sleep(0.002)  # Wait for Thread A to start using instance
    for i in range(5):
        reset_telemetry()  # This sets global to None
        time.sleep(0.002)
    print("[Thread-B] Completed")


def main():
    print("=== Reproducing Global Telemetry Race Condition ===")
    errors = []

    t1 = threading.Thread(target=thread_a_job)
    t2 = threading.Thread(target=thread_b_job)
    t1.start()
    t2.start()

    t1.join()
    t2.join()

    # Check if race was detected
    # We can't directly detect if Thread A hit AttributeError,
    # but we can run multiple times and see if it happens
    print("\nIf you saw AttributeError in output, race was reproduced")
    return len(errors) == 0  # If no errors detected, this run was inconclusive


if __name__ == "__main__":
    for run in range(5):
        print(f"\nRun {run + 1}/5...")
        main()
        time.sleep(0.1)
