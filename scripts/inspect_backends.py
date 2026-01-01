#!/usr/bin/env python3
"""
Inspect Backends Script

This script connects to the running LLM Proxy instance and retrieves
diagnostic information about active backend instances and their models.
"""

import argparse
import sys
import time
from datetime import datetime
from typing import Any

import httpx
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


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


def create_summary_panel(instances: list[dict[str, Any]]) -> Panel:
    """Create a summary panel."""
    total = len(instances)
    active = sum(
        1
        for i in instances
        if i.get("is_functional", True) and not i.get("is_rate_limited", False)
    )
    limited = sum(1 for i in instances if i.get("is_rate_limited", False))
    down = sum(1 for i in instances if not i.get("is_functional", True))

    grid = Table.grid(expand=True)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)
    grid.add_column(justify="center", ratio=1)

    grid.add_row(
        f"[bold]{total}[/bold] Total",
        f"[bold green]{active}[/bold green] Active",
        f"[bold yellow]{limited}[/bold yellow] Rate Limited",
        f"[bold red]{down}[/bold red] Non-Functional",
    )

    return Panel(grid, title="[bold]System Overview[/bold]", border_style="blue")


def display_diagnostics(data: dict[str, Any]) -> None:
    """Display diagnostics using Rich."""
    console = Console()

    timestamp = data.get("timestamp", time.time())
    dt = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    instances = data.get("instances", [])

    # Header
    console.print()
    console.print(
        Panel(
            f"[bold blue]LLM Proxy Inspector[/bold blue]\n[dim]Snapshot at: {dt}[/dim]",
            box=box.DOUBLE,
            border_style="blue",
        )
    )
    console.print()

    if not instances:
        console.print(
            Panel(
                "[yellow]No active backend instances found.[/yellow]",
                title="Status",
                border_style="yellow",
            )
        )
        return

    # Summary
    console.print(create_summary_panel(instances))
    console.print()

    # Group by connector type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for inst in instances:
        ctype = inst.get("connector_type", "unknown")
        if ctype not in by_type:
            by_type[ctype] = []
        by_type[ctype].append(inst)

    # Main Tree
    root = Tree("[bold]Backend Registry[/bold]")

    for ctype, backend_list in sorted(by_type.items()):
        type_node = root.add(
            f"[bold cyan]{ctype.upper()}[/bold cyan] [dim]({len(backend_list)})[/dim]"
        )

        for inst in sorted(backend_list, key=lambda x: str(x.get("name", ""))):  # type: ignore[arg-type]
            name = inst.get("name")
            is_functional = inst.get("is_functional", True)
            is_limited = inst.get("is_rate_limited", False)
            retry_after = inst.get("retry_after_seconds")
            validation_errors = inst.get("validation_errors", [])
            models = inst.get("models", [])

            # Status badge
            if not is_functional:
                status = Text("DOWN", style="bold white on red")
            elif is_limited:
                wait_time = f"{retry_after:.1f}s" if retry_after else "?"
                status = Text(f"LIMITED ({wait_time})", style="bold black on yellow")
            else:
                status = Text("ACTIVE", style="bold white on green")

            # Instance Node
            label = Text.assemble((f"{name} ", "bold"), status)
            inst_node = type_node.add(label)

            # Details
            if validation_errors:
                err_table = Table(box=box.SIMPLE, show_header=False, padding=0)
                for err in validation_errors:
                    err_table.add_row(f"[red]• {err}[/red]")
                inst_node.add(
                    Panel(err_table, title="[red]Errors[/red]", border_style="red")
                )

            # Models
            if models:
                model_count = len(models)
                model_node = inst_node.add(f"Models ({model_count})")

                # Use a simple table for models if there are many
                if model_count > 0:
                    model_names = [m.get("name") for m in models]
                    # Create a grid layout for models
                    model_text = ", ".join(model_names)
                    model_node.add(Text(model_text, style="dim", overflow="fold"))
            else:
                inst_node.add(Text("No models registered", style="italic dim"))

    console.print(root)
    console.print()


def main():
    parser = argparse.ArgumentParser(description="Inspect LLM Proxy Backends")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/v1/diagnostics",
        help="URL of the diagnostics endpoint",
    )
    args = parser.parse_args()

    data = get_diagnostics(args.url)
    display_diagnostics(data)


if __name__ == "__main__":
    main()
