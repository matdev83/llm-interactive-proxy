"""
Performance validation script for context compaction feature.

This script validates NFR 1: "Compaction pass shall add no more than 10 ms p95
per request under typical histories (<=200 messages)."

The script measures compaction performance for various scenarios:
- Small histories (50 messages)
- Typical histories (200 messages)
- Large histories (500 messages - stress test)

Each scenario is run multiple times to capture p95 latency.
"""

import asyncio
import statistics
import time

from src.core.domain.chat import ChatMessage, ToolCall, FunctionCall
from src.core.domain.configuration.compaction_config import CompactionConfig
from src.core.services.history_compaction_service import HistoryCompactionService


def create_test_messages(count: int, content_size: int = 1000) -> list[ChatMessage]:
    """Create test messages with tool calls and results.

    Creates a realistic scenario with:
    - User messages
    - Assistant messages with tool calls
    - Tool result messages (candidates for compaction)

    Args:
        count: Number of total messages to create
        content_size: Size of tool result content in characters

    Returns:
        List of ChatMessage objects
    """
    messages: list[ChatMessage] = []

    # Create message pairs: assistant tool call + tool result
    for i in range(0, count, 2):
        # Assistant message with tool call
        if i + 1 < count:
            tool_call = ToolCall(
                id=f"call_{i}",
                function=FunctionCall(
                    name="read_file",
                    arguments=f'{{"file_path": "src/file_{i//4}.py"}}',
                ),
            )
            messages.append(
                ChatMessage(role="assistant", content="Reading file...", tool_calls=[tool_call])
            )

            # Tool result message
            content = "x" * content_size
            messages.append(
                ChatMessage(
                    role="tool",
                    content=content,
                    tool_call_id=f"call_{i}",
                    name="read_file",
                )
            )

    return messages


async def measure_compaction_time(
    messages: list[ChatMessage],
    config: CompactionConfig,
    iterations: int = 10,
) -> dict[str, float]:
    """Measure compaction performance over multiple iterations.

    Args:
        messages: Test message history
        config: Compaction configuration
        iterations: Number of iterations to run

    Returns:
        Dictionary with statistics (mean, median, p95, min, max) in milliseconds
    """
    service = HistoryCompactionService()
    times_ms: list[float] = []

    # Warm-up run to avoid cold start effects
    await service.compact_history(messages, config)

    # Measure iterations
    for _ in range(iterations):
        start = time.perf_counter()
        await service.compact_history(messages, config)
        elapsed_ms = (time.perf_counter() - start) * 1000
        times_ms.append(elapsed_ms)

    # Calculate statistics
    sorted_times = sorted(times_ms)
    p95_index = int(len(sorted_times) * 0.95)

    return {
        "mean": statistics.mean(times_ms),
        "median": statistics.median(times_ms),
        "p95": sorted_times[p95_index] if p95_index < len(sorted_times) else sorted_times[-1],
        "min": min(times_ms),
        "max": max(times_ms),
    }


async def run_performance_validation() -> dict[str, dict[str, float]]:
    """Run comprehensive performance validation.

    Returns:
        Dictionary mapping scenario names to performance statistics
    """
    # Create test configurations
    config = CompactionConfig.default()
    config.enabled = True  # Ensure compaction is enabled

    # Test scenarios
    scenarios: dict[str, tuple[int, int]] = {
        "small_50_messages": (50, 1000),
        "typical_200_messages": (200, 1000),
        "large_500_messages": (500, 1000),  # Stress test
        "large_content_200": (200, 10000),  # Larger content per message
    }

    results: dict[str, dict[str, float]] = {}

    for scenario_name, (msg_count, content_size) in scenarios.items():
        print(f"\n{'='*60}")
        print(f"Testing scenario: {scenario_name}")
        print(f"  Message count: {msg_count}")
        print(f"  Content size: {content_size} chars")
        print(f"{'='*60}")

        messages = create_test_messages(msg_count, content_size)
        stats = await measure_compaction_time(messages, config)

        # Filter out all_times from stats for the results
        results[scenario_name] = {
            "mean": stats["mean"],
            "median": stats["median"],
            "p95": stats["p95"],
            "min": stats["min"],
            "max": stats["max"],
        }

        print(f"\nPerformance Results ({scenario_name}):")
        print(f"  Mean:    {stats['mean']:.3f} ms")
        print(f"  Median:  {stats['median']:.3f} ms")
        print(f"  P95:     {stats['p95']:.3f} ms")
        print(f"  Min:     {stats['min']:.3f} ms")
        print(f"  Max:     {stats['max']:.3f} ms")

        # Check against NFR
        if msg_count <= 200:
            meets_nfr = stats['p95'] <= 10.0
            print(f"\n  NFR 1 Check (≤10ms p95 for ≤200 messages): {'✓ PASS' if meets_nfr else '✗ FAIL'}")
        else:
            print(f"\n  Note: This scenario exceeds the 200-message NFR threshold")

    return results


def print_summary_report(results: dict[str, dict[str, float]]):
    """Print a summary report of the validation results.

    Args:
        results: Performance statistics for all scenarios
    """
    print(f"\n{'='*60}")
    print("PERFORMANCE VALIDATION SUMMARY REPORT")
    print(f"{'='*60}\n")

    print("NFR 1 Requirement:")
    print("  'Compaction pass shall add no more than 10 ms p95 per request")
    print("   under typical histories (<=200 messages).'\n")

    print("Results:\n")
    for scenario, stats in results.items():
        print(f"  {scenario}:")
        print(f"    P95: {stats['p95']:.3f} ms")
        print(f"    Mean: {stats['mean']:.3f} ms")
        print(f"    Median: {stats['median']:.3f} ms")

    print("\nNFR 1 Compliance Check:")
    nfr_scenarios = {k: v for k, v in results.items() if "200_messages" in k}
    all_pass = all(stats['p95'] <= 10.0 for stats in nfr_scenarios.values())

    for scenario, stats in nfr_scenarios.items():
        status = "✓ PASS" if stats['p95'] <= 10.0 else "✗ FAIL"
        print(f"  {scenario}: {status} (p95={stats['p95']:.3f}ms)")

    print(f"\nOverall NFR 1 Status: {'✓ MET' if all_pass else '✗ NOT MET'}")


async def main():
    """Main entry point for performance validation."""
    print("\nStarting Context Compaction Performance Validation")
    print("=" * 60)

    results = await run_performance_validation()
    print_summary_report(results)

    print("\n" + "=" * 60)
    print("Performance validation complete.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
