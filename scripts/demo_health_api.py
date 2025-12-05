#!/usr/bin/env python
"""Demo script to interact with the /internal/health API endpoint.

This script demonstrates how to query the proxy's health check system
via the REST API and display endpoint health states and backend instance health.

Run with: .venv/Scripts/python.exe scripts/demo_health_api.py [proxy_url]
Default proxy URL: http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import httpx


def format_timestamp(ts: str | None) -> str:
    """Format ISO timestamp for display."""
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f" {title}")
    print("=" * 60)


def print_endpoint_health(endpoint: dict) -> None:
    """Print health information for a single endpoint."""
    api_url = endpoint.get("api_url", "unknown")
    is_healthy = endpoint.get("is_healthy", False)
    ping_ok = endpoint.get("ping_check_success", False)
    http_ok = endpoint.get("http_check_success", False)
    backends = endpoint.get("backends_using_url", [])

    status_emoji = "[OK]" if is_healthy else "[!!]"
    ping_emoji = "[OK]" if ping_ok else "[X]"
    http_emoji = "[OK]" if http_ok else "[X]"

    print(f"\n  {status_emoji} {api_url}")
    print(f"      Overall: {'HEALTHY' if is_healthy else 'UNHEALTHY'}")
    print(f"      Ping: {ping_emoji} {'OK' if ping_ok else 'FAILED'}", end="")
    if endpoint.get("last_ping_latency_ms"):
        print(f" ({endpoint['last_ping_latency_ms']:.1f}ms)", end="")
    if endpoint.get("last_ping_error"):
        print(f" - {endpoint['last_ping_error']}", end="")
    print()

    print(f"      HTTP: {http_emoji} {'OK' if http_ok else 'FAILED'}", end="")
    if endpoint.get("last_http_status_code"):
        print(f" (status {endpoint['last_http_status_code']})", end="")
    if endpoint.get("last_http_latency_ms"):
        print(f" ({endpoint['last_http_latency_ms']:.1f}ms)", end="")
    if endpoint.get("last_http_error"):
        print(f" - {endpoint['last_http_error']}", end="")
    print()

    if endpoint.get("consecutive_ping_failures", 0) > 0:
        print(f"      Consecutive ping failures: {endpoint['consecutive_ping_failures']}")
    if endpoint.get("consecutive_http_failures", 0) > 0:
        print(f"      Consecutive HTTP failures: {endpoint['consecutive_http_failures']}")

    print(f"      Last ping check: {format_timestamp(endpoint.get('last_ping_check_timestamp'))}")
    print(f"      Last HTTP check: {format_timestamp(endpoint.get('last_http_check_timestamp'))}")
    print(f"      Backends using URL: {', '.join(backends) if backends else 'none'}")


def print_backend_health(backends: list[dict]) -> None:
    """Print health information for backend instances."""
    if not backends:
        print("  No backend instances registered for health notifications")
        return

    for backend in backends:
        api_url = backend.get("api_url", "unknown")
        backend_type = backend.get("backend_type", "unknown")
        is_healthy = backend.get("is_endpoint_healthy", True)

        status_emoji = "[OK]" if is_healthy else "[!!]"
        print(f"  {status_emoji} {backend_type}")
        print(f"      API URL: {api_url}")
        print(f"      Endpoint healthy: {'YES' if is_healthy else 'NO'}")


def print_summary(summary: dict) -> None:
    """Print health summary."""
    total = summary.get("total_endpoints", 0)
    healthy = summary.get("healthy_endpoints", 0)
    unhealthy = summary.get("unhealthy_endpoints", 0)

    if total == 0:
        print("  No endpoints registered for health monitoring")
        return

    print(f"  Total endpoints: {total}")
    print(f"  Healthy: {healthy}")
    print(f"  Unhealthy: {unhealthy}")

    if unhealthy > 0:
        print(f"\n  WARNING: {unhealthy} endpoint(s) are currently unhealthy!")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Query the proxy's health check API endpoint"
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
    args = parser.parse_args()

    proxy_url = args.proxy_url.rstrip("/")
    health_url = f"{proxy_url}/internal/health"

    print(f"Querying health endpoint: {health_url}")

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(health_url)
            response.raise_for_status()
            data = response.json()
    except httpx.ConnectError:
        print(f"\nERROR: Could not connect to {proxy_url}")
        print("Make sure the proxy server is running.")
        return 1
    except httpx.HTTPStatusError as e:
        print(f"\nERROR: HTTP {e.response.status_code}")
        return 1
    except Exception as e:
        print(f"\nERROR: {e}")
        return 1

    if args.raw:
        print(json.dumps(data, indent=2))
        return 0

    # Check if service provider is present
    if not data.get("service_provider_present"):
        print("\nWARNING: Service provider not initialized")
        return 1

    print_header("Service Status")
    print(f"  Service Provider: {'OK' if data.get('service_provider_present') else 'NOT PRESENT'}")
    print(f"  IRequestProcessor: {'OK' if data.get('IRequestProcessor_resolvable') else 'ERROR'}")
    print(f"  ChatController: {'OK' if data.get('ChatController_resolvable') else 'ERROR'}")

    # Get endpoint health info
    endpoint_health = data.get("endpoint_health", {})

    if endpoint_health.get("error"):
        print(f"\nHealth check error: {endpoint_health['error']}")
        return 1

    if endpoint_health.get("note"):
        print(f"\nNote: {endpoint_health['note']}")
        return 0

    if not endpoint_health.get("enabled"):
        print("\nHealth check system is not enabled")
        return 0

    print_header("Endpoint Health Summary")
    print_summary(endpoint_health.get("summary", {}))

    endpoints = endpoint_health.get("endpoints", [])
    if endpoints:
        print_header("Endpoint Details")
        for endpoint in endpoints:
            print_endpoint_health(endpoint)

    backends = endpoint_health.get("backends", [])
    if backends:
        print_header("Backend Instance Health")
        print_backend_health(backends)

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

