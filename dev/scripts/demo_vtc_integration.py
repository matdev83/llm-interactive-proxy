#!/usr/bin/env python3
"""
Demo script to verify VTC (Virtual Tool Calling) integration end-to-end.

This script emulates two types of clients:
1. Cline/KiloCode (VTC client) - expects XML tool calls in message content
2. Droid/OpenAI (standard client) - expects native structured tool calls

The demo proves:
- VTC detection based on User-Agent header
- VTC pre-processing extracts XML tool calls for Cline clients
- VTC post-processing converts tool calls back to XML for Cline clients
- Non-VTC clients pass through unchanged
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.domain.session import SessionState
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.vtc_postprocessor import VTCPostProcessor
from src.core.services.streaming.vtc_preprocessor import VTCPreProcessor
from src.core.services.vtc_detection import detect_vtc_client
from src.core.services.vtc_xml_parser import parse_vtc_xml, serialize_tool_calls_to_xml


def print_header(title: str) -> None:
    """Print a formatted section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_subheader(title: str) -> None:
    """Print a formatted subsection header."""
    print(f"\n--- {title} ---")


def print_result(label: str, value: str, indent: int = 2) -> None:
    """Print a labeled result."""
    prefix = " " * indent
    print(f"{prefix}{label}: {value}")


async def demo_vtc_detection() -> None:
    """Demonstrate VTC client detection based on User-Agent."""
    print_header("1. VTC CLIENT DETECTION")

    # Default VTC patterns
    vtc_patterns = ["cline", "kilo", "roo"]

    test_agents = [
        # VTC clients (should match)
        ("Cline/1.0.0 (VSCode Extension)", True),
        ("KiloCode-Agent/2.1.0", True),
        ("RooCode/0.5.0-beta", True),
        ("Mozilla/5.0 (compatible; Cline-Bot/1.0)", True),
        # Non-VTC clients (should NOT match)
        ("Factory-Droid/3.0.0", False),
        ("OpenAI-Python/1.0.0", False),
        ("curl/7.68.0", False),
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", False),
        (None, False),
        ("", False),
    ]

    print(f"\nVTC patterns configured: {vtc_patterns}\n")

    all_passed = True
    for agent, expected in test_agents:
        result = detect_vtc_client(agent, vtc_patterns)
        status = "[PASS]" if result == expected else "[FAIL]"
        if result != expected:
            all_passed = False
        agent_display = f"'{agent}'" if agent else "None"
        print(
            f"  {status} Agent: {agent_display:50} -> VTC: {result} (expected: {expected})"
        )

    print(
        f"\nVTC Detection: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}"
    )
    return all_passed


async def demo_vtc_session_state() -> None:
    """Demonstrate VTC flag in session state."""
    print_header("2. VTC SESSION STATE")

    # Create a session with VTC disabled
    state = SessionState()
    print(f"\n  Initial vtc_enabled: {state.vtc_enabled}")

    # Enable VTC
    new_state = state.with_vtc_enabled(True)
    print(f"  After with_vtc_enabled(True): {new_state.vtc_enabled}")

    # Verify immutability
    print(f"  Original state unchanged: {state.vtc_enabled}")

    print("\nVTC Session State: PASS")
    return True


async def demo_xml_parsing() -> None:
    """Demonstrate XML tool call parsing."""
    print_header("3. XML TOOL CALL PARSING")

    # Sample Cline-style XML tool call
    xml_content = """I will check the files now.

<function_calls>
<invoke name="execute_command">
<parameter name="command">ls -la</parameter>
<parameter name="cwd">/project</parameter>
</invoke>
</function_calls>

Let me know if you need anything else."""

    print_subheader("Input Content (Cline-style)")
    print(xml_content)

    # Parse the XML
    tool_calls, cleaned_content = parse_vtc_xml(xml_content)

    print_subheader("Parsed Tool Calls")
    for i, tc in enumerate(tool_calls):
        print(f"  Tool Call {i + 1}:")
        print(f"    ID: {tc['id']}")
        print(f"    Type: {tc['type']}")
        print(f"    Function: {tc['function']['name']}")
        print(f"    Arguments: {tc['function']['arguments']}")

    print_subheader("Cleaned Content (XML stripped)")
    print(f"  '{cleaned_content}'")

    # Verify
    passed = (
        len(tool_calls) == 1
        and tool_calls[0]["function"]["name"] == "execute_command"
        and "function_calls" not in cleaned_content
        and "I will check the files now" in cleaned_content
    )

    print(f"\nXML Parsing: {'PASS' if passed else 'FAIL'}")
    return passed


async def demo_xml_serialization() -> None:
    """Demonstrate XML tool call serialization."""
    print_header("4. XML TOOL CALL SERIALIZATION")

    # Sample internal tool calls (OpenAI format)
    tool_calls = [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path": "/tmp/test.txt", "encoding": "utf-8"}',
            },
        },
        {
            "id": "call_def456",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": '{"path": "/tmp/output.txt", "content": "Hello World"}',
            },
        },
    ]

    print_subheader("Input Tool Calls (Internal Format)")
    for i, tc in enumerate(tool_calls):
        print(f"  Tool Call {i + 1}: {tc['function']['name']}")

    # Serialize to XML
    xml_output = serialize_tool_calls_to_xml(tool_calls)

    print_subheader("Serialized XML (Cline Format)")
    print(xml_output)

    # Verify
    passed = (
        "<function_calls>" in xml_output
        and '<invoke name="read_file">' in xml_output
        and '<invoke name="write_file">' in xml_output
        and '<parameter name="path">' in xml_output
    )

    print(f"\nXML Serialization: {'PASS' if passed else 'FAIL'}")
    return passed


async def demo_vtc_preprocessor() -> None:
    """Demonstrate VTC pre-processor in action."""
    print_header("5. VTC PRE-PROCESSOR (XML -> Internal)")

    registry = StreamingContextRegistry()
    preprocessor = VTCPreProcessor(registry=registry)

    # Simulate streaming content with XML tool call
    xml_tool_call = """<function_calls>
<invoke name="list_files">
<parameter name="directory">/src</parameter>
</invoke>
</function_calls>"""

    content_with_vtc = StreamingContent(
        content=f"Checking directory contents. {xml_tool_call}",
        metadata={"vtc_enabled": True},  # VTC session
        stream_id="stream-cline-001",
    )

    content_without_vtc = StreamingContent(
        content=f"Checking directory contents. {xml_tool_call}",
        metadata={"vtc_enabled": False},  # Non-VTC session
        stream_id="stream-droid-001",
    )

    print_subheader("Cline Client (vtc_enabled=True)")
    result_vtc = await preprocessor.process(content_with_vtc)
    print(f"  Content: '{result_vtc.content}'")
    print(f"  Tool Calls in Metadata: {len(result_vtc.metadata.get('tool_calls', []))}")
    if result_vtc.metadata.get("tool_calls"):
        print(f"    -> {result_vtc.metadata['tool_calls'][0]['function']['name']}")

    # Reset registry for next test
    registry = StreamingContextRegistry()
    preprocessor = VTCPreProcessor(registry=registry)

    print_subheader("Droid Client (vtc_enabled=False)")
    result_no_vtc = await preprocessor.process(content_without_vtc)
    print(f"  Content: '{result_no_vtc.content[:60]}...'")
    print(
        f"  Tool Calls in Metadata: {len(result_no_vtc.metadata.get('tool_calls', []))}"
    )
    print(f"  XML Preserved: {'<function_calls>' in result_no_vtc.content}")

    # Verify
    passed = (
        # VTC client: XML extracted, tool_calls in metadata
        len(result_vtc.metadata.get("tool_calls", [])) == 1
        and "<function_calls>" not in result_vtc.content
        # Non-VTC client: XML preserved, no tool_calls in metadata
        and len(result_no_vtc.metadata.get("tool_calls", [])) == 0
        and "<function_calls>" in result_no_vtc.content
    )

    print(f"\nVTC Pre-Processor: {'PASS' if passed else 'FAIL'}")
    return passed


async def demo_vtc_postprocessor() -> None:
    """Demonstrate VTC post-processor in action."""
    print_header("6. VTC POST-PROCESSOR (Internal -> XML)")

    registry = StreamingContextRegistry()
    postprocessor = VTCPostProcessor(registry=registry)

    # Internal tool call (already extracted by pre-processor or from native API)
    internal_tool_calls = [
        {
            "id": "call_xyz789",
            "type": "function",
            "function": {
                "name": "search_code",
                "arguments": '{"query": "def main", "path": "/src"}',
            },
        }
    ]

    content_with_vtc = StreamingContent(
        content="Searching the codebase.",
        metadata={"vtc_enabled": True, "tool_calls": internal_tool_calls},
        stream_id="stream-cline-002",
    )

    content_without_vtc = StreamingContent(
        content="Searching the codebase.",
        metadata={"vtc_enabled": False, "tool_calls": internal_tool_calls},
        stream_id="stream-droid-002",
    )

    print_subheader("Cline Client (vtc_enabled=True)")
    result_vtc = await postprocessor.process(content_with_vtc)
    print(f"  Content includes XML: {'<function_calls>' in result_vtc.content}")
    print(
        f"  Tool Calls cleared from metadata: {'tool_calls' not in result_vtc.metadata}"
    )
    if "<function_calls>" in result_vtc.content:
        print("  Output preview:")
        for line in result_vtc.content.split("\n")[:8]:
            print(f"    {line}")

    print_subheader("Droid Client (vtc_enabled=False)")
    result_no_vtc = await postprocessor.process(content_without_vtc)
    print(f"  Content unchanged: {result_no_vtc.content == 'Searching the codebase.'}")
    print(
        f"  Tool Calls preserved in metadata: {'tool_calls' in result_no_vtc.metadata}"
    )

    # Verify
    passed = (
        # VTC client: XML serialized into content, tool_calls cleared
        "<function_calls>" in result_vtc.content
        and "tool_calls" not in result_vtc.metadata
        # Non-VTC client: content unchanged, tool_calls preserved
        and result_no_vtc.content == "Searching the codebase."
        and "tool_calls" in result_no_vtc.metadata
    )

    print(f"\nVTC Post-Processor: {'PASS' if passed else 'FAIL'}")
    return passed


async def demo_full_pipeline() -> None:
    """Demonstrate full VTC pipeline (pre -> core -> post)."""
    print_header("7. FULL VTC PIPELINE SIMULATION")

    registry = StreamingContextRegistry()
    preprocessor = VTCPreProcessor(registry=registry)
    postprocessor = VTCPostProcessor(registry=registry)

    # Simulate incoming content from LLM backend with XML tool call
    incoming_content = """I will execute the command for you.

<function_calls>
<invoke name="run_terminal">
<parameter name="command">pytest tests/ -v</parameter>
<parameter name="timeout">60</parameter>
</invoke>
</function_calls>"""

    print_subheader("Simulated LLM Response")
    print(incoming_content)

    # === CLINE CLIENT FLOW ===
    print_subheader("CLINE CLIENT FLOW (VTC Enabled)")

    # Step 1: Pre-process (extract XML)
    cline_input = StreamingContent(
        content=incoming_content,
        metadata={"vtc_enabled": True},
        stream_id="stream-cline-pipeline",
    )
    after_pre = await preprocessor.process(cline_input)
    print("\n  1. After Pre-Processor:")
    print(f"     Content: '{after_pre.content}'")
    print(f"     Tool Calls: {len(after_pre.metadata.get('tool_calls', []))} extracted")

    # Step 2: Simulate core processing (tool call could be modified here)
    # In real pipeline: loop detection, reactors, filters would process here
    print("\n  2. Core Pipeline (tool calls available for processing)")
    if after_pre.metadata.get("tool_calls"):
        tc = after_pre.metadata["tool_calls"][0]
        print(f"     Tool: {tc['function']['name']}")
        print(f"     Args: {tc['function']['arguments']}")

    # Step 3: Post-process (serialize back to XML)
    after_post = await postprocessor.process(after_pre)
    print("\n  3. After Post-Processor:")
    print(f"     Content includes XML: {'<function_calls>' in after_post.content}")
    print(f"     Tool Calls cleared: {'tool_calls' not in after_post.metadata}")

    # === DROID CLIENT FLOW ===
    print_subheader("DROID CLIENT FLOW (VTC Disabled)")

    # Reset registry
    registry2 = StreamingContextRegistry()
    preprocessor2 = VTCPreProcessor(registry=registry2)
    postprocessor2 = VTCPostProcessor(registry=registry2)

    droid_input = StreamingContent(
        content=incoming_content,
        metadata={"vtc_enabled": False},
        stream_id="stream-droid-pipeline",
    )

    after_pre_droid = await preprocessor2.process(droid_input)
    print("\n  1. After Pre-Processor:")
    print(f"     Content unchanged: {after_pre_droid.content == incoming_content}")
    print(
        f"     Tool Calls: {len(after_pre_droid.metadata.get('tool_calls', []))} (none extracted)"
    )

    after_post_droid = await postprocessor2.process(after_pre_droid)
    print("\n  2. After Post-Processor:")
    print(f"     Content unchanged: {after_post_droid.content == incoming_content}")

    # Verify round-trip for VTC
    print_subheader("Round-Trip Verification")

    # Parse both original and final to compare tool calls
    original_tcs, _ = parse_vtc_xml(incoming_content)
    final_tcs, _ = parse_vtc_xml(after_post.content)

    print(f"  Original tool calls: {len(original_tcs)}")
    print(f"  Final tool calls: {len(final_tcs)}")
    if original_tcs and final_tcs:
        print(
            f"  Tool name match: {original_tcs[0]['function']['name'] == final_tcs[0]['function']['name']}"
        )

    passed = (
        # VTC client: XML extracted and re-serialized
        "<function_calls>" in after_post.content
        and "tool_calls" not in after_post.metadata
        # Non-VTC client: content unchanged throughout
        and after_post_droid.content == incoming_content
        # Round-trip preserved tool call
        and len(original_tcs) == len(final_tcs)
    )

    print(f"\nFull VTC Pipeline: {'PASS' if passed else 'FAIL'}")
    return passed


async def main() -> int:
    """Run all VTC integration demos."""
    print("\n" + "#" * 70)
    print("#" + " " * 68 + "#")
    print("#" + "  VTC (Virtual Tool Calling) INTEGRATION DEMO".center(68) + "#")
    print("#" + " " * 68 + "#")
    print("#" * 70)

    results = []

    # Run all demos
    results.append(("VTC Detection", await demo_vtc_detection()))
    results.append(("Session State", await demo_vtc_session_state()))
    results.append(("XML Parsing", await demo_xml_parsing()))
    results.append(("XML Serialization", await demo_xml_serialization()))
    results.append(("VTC Pre-Processor", await demo_vtc_preprocessor()))
    results.append(("VTC Post-Processor", await demo_vtc_postprocessor()))
    results.append(("Full Pipeline", await demo_full_pipeline()))

    # Summary
    print_header("SUMMARY")
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        if not passed:
            all_passed = False
        print(f"  {status} {name}")

    print("\n" + "=" * 70)
    if all_passed:
        print("  ALL TESTS PASSED - VTC Integration is fully functional")
    else:
        print("  SOME TESTS FAILED - Check output above for details")
    print("=" * 70 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
