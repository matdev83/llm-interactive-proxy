# mypy: disable-error-code="arg-type,attr-defined,union-attr,call-overload"
#!/usr/bin/env python3
"""
Usage Report Script

Generates a usage breakdown by backend and model for the current day (UTC).
Tracks tokens submitted to and received from LLM backends (remote usage).
"""

import argparse
import asyncio
import contextlib
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config.app_config import load_config
from src.core.database.engine import init_database
from src.core.database.models.usage import SessionMetricsTable, UsageRecordTable
from src.core.domain.traffic_leg import TrafficLeg


async def generate_report(config_path: str | None = None) -> None:
    """Generate and print the usage report."""
    console = Console()

    # Load configuration
    try:
        config = load_config(config_path)
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        return

    # Initialize database
    try:
        engine = await init_database(config.database)
    except Exception as e:
        console.print(f"[red]Error initializing database: {e}[/red]")
        return

    # Define time range (today UTC)
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    console.print("[bold blue]Usage Report[/bold blue]")
    console.print(f"Date: [cyan]{start_of_day.strftime('%Y-%m-%d')}[/cyan] (UTC)")
    console.print(f"Database: [dim]{config.database.url}[/dim]")
    console.print()

    # Try to import CBOR inspection tools
    try:
        import cbor2

        from scripts.inspect_cbor_capture import load_capture_file, parse_all_sse_events
        cbor_available = True
    except ImportError:
        cbor_available = False

    async with engine.session() as session:
        # First, try to query detailed UsageRecords
        stmt_detailed = (
            select(
                UsageRecordTable.backend_type,  # type: ignore[arg-type]
                UsageRecordTable.model,  # type: ignore[arg-type]
                func.count().label("request_count"),
                func.sum(UsageRecordTable.mutated_prompt_tokens).label("tokens_submitted"),
                func.sum(UsageRecordTable.verbatim_completion_tokens).label("tokens_received"),
            )
            .where(UsageRecordTable.leg == TrafficLeg.PROXY_TO_BACKEND.value)
            .where(UsageRecordTable.timestamp >= start_of_day)
            .group_by(UsageRecordTable.backend_type, UsageRecordTable.model)
            .order_by(UsageRecordTable.backend_type, UsageRecordTable.model)
        )

        result_detailed = await session.execute(stmt_detailed)
        rows_detailed = result_detailed.all()

        if rows_detailed:
            _print_detailed_table(console, rows_detailed)
        else:
            # Fallback to SessionMetrics
            stmt_sessions = (
                select(
                    SessionMetricsTable.backend_type,  # type: ignore[arg-type]
                    SessionMetricsTable.model,  # type: ignore[arg-type]
                    func.count().label("session_count"),
                    func.sum(SessionMetricsTable.total_tokens).label("total_tokens"),
                )
                .where(SessionMetricsTable.last_activity >= start_of_day)
                .group_by(SessionMetricsTable.backend_type, SessionMetricsTable.model)
                .order_by(SessionMetricsTable.backend_type, SessionMetricsTable.model)
            )

            result_sessions = await session.execute(stmt_sessions)
            rows_sessions = result_sessions.all()

            # We only use session fallback if there's actual token data
            has_tokens = any((row.total_tokens or 0) > 0 for row in rows_sessions)

            if rows_sessions and has_tokens:
                console.print("[yellow]Detailed usage records not found. Falling back to session metrics.[/yellow]")
                console.print("[dim](Note: Prompt/Completion breakdown is not available in session metrics)[/dim]")
                console.print()
                _print_session_table(console, rows_sessions)
            elif cbor_available:
                # Fallback to CBOR analysis
                console.print("[yellow]No usage data found in database. Analyzing wire captures...[/yellow]")
                console.print()
                await _analyze_cbor_captures(console, start_of_day)
            else:
                console.print("[yellow]No usage recorded for today (database empty).[/yellow]")
                if not cbor_available:
                    console.print("[dim]Install 'cbor2' to enable wire capture analysis fallback.[/dim]")

    await engine.close()


async def _analyze_cbor_captures(console: Console, start_time: datetime) -> None:
    """Analyze CBOR capture files for usage data."""
    from pathlib import Path
    
    # Import here to ensure they are available
    from scripts.inspect_cbor_capture import load_capture_file, parse_all_sse_events

    capture_dir = Path("var/wire_captures_cbor")
    if not capture_dir.exists():
        console.print("[red]Wire capture directory not found.[/red]")
        return

    # Find files modified today
    files = []
    start_ts = start_time.timestamp()
    
    for file_path in capture_dir.glob("*.cbor"):
        try:
            mtime = file_path.stat().st_mtime
            if mtime >= start_ts:
                files.append(file_path)
        except OSError:
            continue

    if not files:
        console.print("[yellow]No wire captures found for today.[/yellow]")
        return

    console.print(f"Scanning [bold]{len(files)}[/bold] capture file(s) for usage events...")
    
    # Stats aggregation
    stats: dict[tuple[str, str], dict[str, int]] = {}
    
    for file_path in files:
        try:
            header, entries = load_capture_file(file_path)
            
            # Group entries by session to correlate request/response
            sessions: dict[str, dict[str, Any]] = {}

            for entry in entries:
                ts = entry.get("ts", 0)
                if ts < start_ts:
                    continue
                
                meta = entry.get("meta", {})
                sid = meta.get("sid")
                if not sid:
                    continue

                if sid not in sessions:
                    sessions[sid] = {
                        "backend": meta.get("be", "unknown"),
                        "model": "unknown",
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "requests": 0
                    }

                direction = entry.get("dir")
                data = entry.get("data", b"")

                if direction == 2: # PROXY_TO_BACKEND
                    sessions[sid]["requests"] += 1
                    # Estimate prompt tokens if not already known
                    # (Will be overwritten by explicit usage from backend if available)
                    if sessions[sid]["prompt_tokens"] == 0:
                        sessions[sid]["prompt_tokens"] = len(data) // 4

                elif direction == 3: # BACKEND_TO_PROXY
                    # Try to extract usage from SSE events
                    events = parse_all_sse_events(data)
                    for event in events:
                        if "model" in event:
                            sessions[sid]["model"] = event["model"]
                        
                        usage = event.get("usage")
                        if usage:
                            p = usage.get("prompt_tokens")
                            c = usage.get("completion_tokens")
                            if p is not None: sessions[sid]["prompt_tokens"] = p
                            if c is not None: sessions[sid]["completion_tokens"] = c
                    
                    if not events and sessions[sid]["completion_tokens"] == 0:
                        sessions[sid]["completion_tokens"] += len(data) // 4

            # Aggregate session stats into global stats
            for s_data in sessions.values():
                if s_data["requests"] == 0:
                    continue
                    
                key = (s_data["backend"], s_data["model"])
                if key not in stats:
                    stats[key] = {"requests": 0, "p": 0, "c": 0}
                
                stats[key]["requests"] += s_data["requests"]
                stats[key]["p"] += s_data["prompt_tokens"]
                stats[key]["c"] += s_data["completion_tokens"]

        except Exception as e:
            console.print(f"[red]Error reading {file_path.name}: {e}[/red]")

    if not stats:
        console.print("[yellow]No usage found in wire captures.[/yellow]")
        return

    # Convert to list for display
    rows = []
    for (backend, model), data in stats.items():
        class Row:
            def __init__(self, b, m, r, p, c):
                self.backend_type = b
                self.model = m
                self.request_count = r
                self.tokens_submitted = p
                self.tokens_received = c
        
        rows.append(Row(backend, model, data["requests"], data["p"], data["c"]))

    _print_detailed_table(console, rows)


def _print_detailed_table(console: Console, rows: Sequence[Any]) -> None:
    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("Backend", style="cyan", overflow="fold")
    table.add_column("Model", style="green", overflow="fold")
    table.add_column("Requests", justify="right")
    table.add_column("Tokens Submitted", justify="right")
    table.add_column("Tokens Received", justify="right")
    table.add_column("Total Tokens", justify="right", style="bold")

    total_requests = 0
    total_submitted = 0
    total_received = 0

    for row in rows:
        backend_type = row.backend_type
        model = row.model
        requests = row.request_count
        submitted = row.tokens_submitted or 0
        received = row.tokens_received or 0
        total = submitted + received

        total_requests += requests
        total_submitted += submitted
        total_received += received

        table.add_row(
            backend_type,
            model,
            f"{requests:,}",
            f"{submitted:,}",
            f"{received:,}",
            f"{total:,}",
        )

    table.add_section()
    table.add_row(
        "TOTAL",
        "",
        f"{total_requests:,}",
        f"{total_submitted:,}",
        f"{total_received:,}",
        f"{total_submitted + total_received:,}",
        style="bold white",
    )

    console.print(table)


def _print_session_table(console: Console, rows: Sequence[Any]) -> None:
    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("Backend", style="cyan", overflow="fold")
    table.add_column("Model", style="green", overflow="fold")
    table.add_column("Sessions", justify="right")
    table.add_column("Total Tokens", justify="right", style="bold")

    total_sessions = 0
    total_tokens = 0

    for row in rows:
        backend_type = row.backend_type or "unknown"
        model = row.model or "unknown"
        sessions = row.session_count
        tokens = row.total_tokens or 0

        total_sessions += sessions
        total_tokens += tokens

        table.add_row(
            backend_type,
            model,
            f"{sessions:,}",
            f"{tokens:,}",
        )

    table.add_section()
    table.add_row(
        "TOTAL",
        "",
        f"{total_sessions:,}",
        f"{total_tokens:,}",
        style="bold white",
    )

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Generate usage report")
    parser.add_argument("--config", help="Path to configuration file")
    args = parser.parse_args()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(generate_report(args.config))


if __name__ == "__main__":
    main()
