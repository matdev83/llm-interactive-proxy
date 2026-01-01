#!/usr/bin/env python
"""Inspect real-time connection activity through backend connectors.

This script queries the proxy's diagnostics endpoint to display current
connection activity with RX/TX byte counters per session.

Run with: .venv/Scripts/python.exe scripts/inspect_activity.py [proxy_url]
Default proxy URL: http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any

import httpx

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    _has_rich_flag = True
except ImportError:
    _has_rich_flag = False
    # Define placeholders for type checking - these will only be used when HAS_RICH is False
    box = None  # type: ignore[assignment, misc]
    Console = None  # type: ignore[assignment, misc]
    Panel = None  # type: ignore[assignment, misc]
    Table = None  # type: ignore[assignment, misc]

HAS_RICH = _has_rich_flag


def format_bytes(num_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    else:
        return f"{num_bytes / (1024 * 1024):.2f} MB"


def format_duration(seconds: float) -> str:
    """Format duration into human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def get_diagnostics(url: str) -> dict[str, Any]:
    """Fetch diagnostics from the API."""
    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]
    except httpx.RequestError as e:
        print(f"Error connecting to {url}: {e}")
        print("Is the LLM Proxy server running?")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error {e.response.status_code}: {e.response.text}")
        sys.exit(1)


def print_activity_plain(data: dict[str, Any]) -> None:
    """Print activity information without Rich formatting."""
    timestamp = data.get("timestamp", time.time())
    dt = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n=== Connection Activity Report ({dt}) ===\n")

    # Check if activity tracking is enabled
    tracking_enabled = data.get("activity_tracking_enabled", False)
    if not tracking_enabled:
        print("NOTE: Activity tracking is DISABLED.")
        print("Enable with: --enable-activity-tracking or ENABLE_ACTIVITY_TRACKING=1")
        print()
        return

    global_activity = data.get("global_activity")
    if global_activity:
        if not global_activity.get("enabled", True):
            print("NOTE: Activity tracking is DISABLED.")
            print(
                "Enable with: --enable-activity-tracking or ENABLE_ACTIVITY_TRACKING=1"
            )
            print()
            return

        print("Global Activity:")
        print(
            f"  Active Connections: {global_activity.get('total_active_connections', 0)}"
        )
        print(
            f"  Total Bytes RX: {format_bytes(global_activity.get('total_bytes_rx', 0))}"
        )
        print(
            f"  Total Bytes TX: {format_bytes(global_activity.get('total_bytes_tx', 0))}"
        )
        print()

    instances = data.get("instances", [])
    if not instances:
        print("No backend instances found.")
        return

    for instance in instances:
        name = instance.get("name", "unknown")
        activity = instance.get("activity")

        if activity is None:
            continue

        connections = activity.get("connections", [])
        if not connections:
            continue

        print(f"Backend: {name}")
        print(f"  Active Connections: {activity.get('active_connections', 0)}")
        print(f"  Total RX: {format_bytes(activity.get('total_bytes_rx', 0))}")
        print(f"  Total TX: {format_bytes(activity.get('total_bytes_tx', 0))}")
        print()

        for conn in connections:
            session_id = conn.get("session_id", "unknown")[:16]
            conn_type = conn.get("connection_type", "unknown")
            duration = conn.get("duration_seconds", 0)
            model = conn.get("model", "")
            bytes_rx = conn.get("bytes_rx", 0)
            bytes_tx = conn.get("bytes_tx", 0)

            print(f"    Session: {session_id}...")
            print(f"      Type: {conn_type}")
            if model:
                print(f"      Model: {model}")
            print(f"      Duration: {format_duration(duration)}")
            print(f"      RX: {format_bytes(bytes_rx)} | TX: {format_bytes(bytes_tx)}")
            print()


def create_activity_table(data: dict[str, Any]) -> Any:  # type: ignore[return-type]
    """Create a Rich table showing activity."""
    if not HAS_RICH:
        raise ImportError("rich library is required for this function")
    table = Table(
        title="Active Connections",
        box=box.ROUNDED,  # type: ignore[union-attr]
        show_header=True,
        header_style="bold cyan",
    )

    table.add_column("Backend", style="green", no_wrap=True)
    table.add_column("Session", style="dim")
    table.add_column("Type", style="yellow")
    table.add_column("Model", style="blue")
    table.add_column("Duration", justify="right")
    table.add_column("RX", justify="right", style="green")
    table.add_column("TX", justify="right", style="magenta")

    instances = data.get("instances", [])
    for instance in instances:
        name = instance.get("name", "unknown")
        activity = instance.get("activity")

        if activity is None:
            continue

        connections = activity.get("connections", [])
        for conn in connections:
            session_id = conn.get("session_id", "unknown")[:12] + "..."
            conn_type = conn.get("connection_type", "?")
            duration = format_duration(conn.get("duration_seconds", 0))
            model = conn.get("model", "-") or "-"
            bytes_rx = format_bytes(conn.get("bytes_rx", 0))
            bytes_tx = format_bytes(conn.get("bytes_tx", 0))

            table.add_row(
                name,
                session_id,
                conn_type,
                model,
                duration,
                bytes_rx,
                bytes_tx,
            )

    return table


def create_summary_panel(data: dict[str, Any]) -> Any:  # type: ignore[return-type]
    """Create a Rich panel showing summary."""
    if not HAS_RICH:
        raise ImportError("rich library is required for this function")
    # Check if activity tracking is enabled
    tracking_enabled = data.get("activity_tracking_enabled", False)
    global_activity = data.get("global_activity", {})

    timestamp = data.get("timestamp", time.time())
    dt = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")

    if not tracking_enabled or not global_activity.get("enabled", True):
        content = (
            "[yellow]Activity tracking is DISABLED[/yellow]\n"
            "[dim]Enable with: --enable-activity-tracking or ENABLE_ACTIVITY_TRACKING=1[/dim]"
        )
        return Panel(content, title="Connection Activity", border_style="yellow")  # type: ignore[misc]

    total_conn = global_activity.get("total_active_connections", 0)
    total_rx = format_bytes(global_activity.get("total_bytes_rx", 0))
    total_tx = format_bytes(global_activity.get("total_bytes_tx", 0))

    content = (
        f"[bold]Active Connections:[/bold] {total_conn}  |  "
        f"[green]Total RX:[/green] {total_rx}  |  "
        f"[magenta]Total TX:[/magenta] {total_tx}  |  "
        f"[dim]Updated: {dt}[/dim]"
    )

    return Panel(content, title="Connection Activity", border_style="blue")  # type: ignore[misc]


def display_activity_rich(data: dict[str, Any]) -> Any:  # type: ignore[return-type]
    """Display activity using Rich."""
    if not HAS_RICH:
        raise ImportError("rich library is required for this function")
    console = Console()  # type: ignore[misc]
    console.clear()

    console.print(create_summary_panel(data))
    console.print()

    table = create_activity_table(data)
    if table.row_count > 0:
        console.print(table)
    else:
        console.print("[dim]No active connections[/dim]")

    return console


def watch_activity(url: str, interval: float = 1.0) -> None:
    """Watch activity in real-time with auto-refresh."""
    if not HAS_RICH:
        print("Real-time watch requires the 'rich' library.")
        print("Install with: pip install rich")
        sys.exit(1)

    console = Console()  # type: ignore[misc]

    console.print("[dim]Press Ctrl+C to stop watching...[/dim]\n")

    try:
        while True:
            console.clear()
            data = get_diagnostics(url)
            console.print(create_summary_panel(data))
            console.print()

            table = create_activity_table(data)
            if table.row_count > 0:
                console.print(table)
            else:
                console.print("[dim]No active connections[/dim]")

            console.print(
                f"\n[dim]Refreshing every {interval}s... (Ctrl+C to stop)[/dim]"
            )
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped watching.[/yellow]")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect real-time connection activity through backend connectors"
    )
    parser.add_argument(
        "proxy_url",
        nargs="?",
        default="http://localhost:8000",
        help="Proxy server URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Output raw JSON response",
    )
    parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Watch activity in real-time (requires 'rich' library)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=float,
        default=1.0,
        help="Refresh interval in seconds for watch mode (default: 1.0)",
    )
    args = parser.parse_args()

    proxy_url = args.proxy_url.rstrip("/")
    diagnostics_url = f"{proxy_url}/v1/diagnostics"

    if args.watch:
        watch_activity(diagnostics_url, args.interval)
        return 0

    print(f"Querying diagnostics endpoint: {diagnostics_url}")
    data = get_diagnostics(diagnostics_url)

    if args.raw:
        print(json.dumps(data, indent=2))
        return 0

    if HAS_RICH:
        display_activity_rich(data)
    else:
        print_activity_plain(data)

    return 0


if __name__ == "__main__":
    sys.exit(main())
