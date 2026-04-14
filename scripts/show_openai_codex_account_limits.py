#!/usr/bin/env python3
"""Display OpenAI Codex managed OAuth accounts with last-seen limit telemetry.

Reads the same on-disk account store as ``manage_openai_codex_accounts.py``.
``last_codex_quota_headers`` / ``last_codex_usage_limit`` are populated while the
proxy runs (from Codex responses and ``usage_limit_reached`` handling); this
script does not call OpenAI and does not start the proxy.

Quota header snapshots are written to disk at most once per 60 seconds per
account during normal traffic; ``usage_limit_reached`` (HTTP 429) updates for
that account are written immediately.

Example::

    ./.venv/Scripts/python.exe scripts/show_openai_codex_account_limits.py
    ./.venv/Scripts/python.exe scripts/show_openai_codex_account_limits.py --json
    ./.venv/Scripts/python.exe scripts/show_openai_codex_account_limits.py --account-id myacct
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.connectors.openai_codex.managed_oauth_constants import DEFAULT_STORAGE_PATH
from src.connectors.openai_codex.managed_oauth_storage import ManagedOAuthStorageService


def _format_ms(ms: int | None) -> str:
    if ms is None:
        return "-"
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return dt.isoformat()
    except (OSError, OverflowError, ValueError):
        return str(ms)


def _summarize_quota_headers(headers: dict[str, str] | None) -> str:
    if not headers:
        return "-"
    keys = sorted(headers.keys())
    if len(keys) <= 3:
        return ", ".join(
            f"{k}={headers[k][:24]}..." if len(headers[k]) > 24 else f"{k}={headers[k]}"
            for k in keys
        )
    preview = keys[:3]
    parts = [
        f"{k}={headers[k][:16]}..." if len(headers[k]) > 16 else f"{k}={headers[k]}"
        for k in preview
    ]
    return ", ".join(parts) + f", +{len(keys) - 3} more"


def _summarize_usage_limit(blob: dict[str, object] | None) -> str:
    if not blob:
        return "-"
    plan = blob.get("plan_type") or "?"
    rsec = blob.get("resets_in_seconds")
    obs = blob.get("observed_at") or "?"
    return f"plan={plan} resets_in_s={rsec} @ {obs}"


async def cmd_show_limits(
    storage: ManagedOAuthStorageService, args: argparse.Namespace
) -> None:
    accounts = await storage.load_all_accounts()
    if args.account_id:
        accounts = [a for a in accounts if a.account_id == args.account_id]
        if not accounts:
            print(f"No account with id {args.account_id!r} found.", file=sys.stderr)
            sys.exit(1)

    if not accounts:
        print("No managed OpenAI Codex accounts found.")
        print("Use scripts/manage_openai_codex_accounts.py add to authorize accounts.")
        return

    rows: list[dict[str, object]] = []
    for acc in sorted(accounts, key=lambda a: a.account_id):
        rows.append(
            {
                "account_id": acc.account_id,
                "email": acc.email,
                "chatgpt_account_id": acc.chatgpt_account_id,
                "status": acc.status,
                "rate_limited_until_utc": _format_ms(acc.rate_limited_until),
                "last_codex_quota_observed_at": acc.last_codex_quota_observed_at,
                "last_codex_quota_headers": acc.last_codex_quota_headers,
                "last_codex_usage_limit": acc.last_codex_usage_limit,
            }
        )

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    print(
        "Last-seen Codex limits (empty until the proxy handles traffic for each account).\n"
    )
    header = (
        f"{'Account':<20} {'Email':<28} {'Status':<14} "
        f"{'RateLimitUntil':<22} {'QuotaSeen':<20} {'UsageLimit':<48}"
    )
    print(header)
    print("-" * len(header))
    for acc in sorted(accounts, key=lambda a: a.account_id):
        email = (acc.email or "-")[:26]
        qseen = (acc.last_codex_quota_observed_at or "-")[:18]
        rlu = _format_ms(acc.rate_limited_until)
        print(
            f"{acc.account_id:<20} {email:<28} {acc.status:<14} "
            f"{rlu:<22} "
            f"{qseen:<20} {_summarize_usage_limit(acc.last_codex_usage_limit):<48}"
        )
        if acc.last_codex_quota_headers:
            print(
                f"  x-codex headers: {_summarize_quota_headers(acc.last_codex_quota_headers)}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show managed OpenAI Codex accounts with last-seen limit telemetry"
    )
    parser.add_argument(
        "--storage-path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Managed account directory (default: {DEFAULT_STORAGE_PATH})",
    )
    parser.add_argument("--account-id", help="Only show this managed account_id")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    storage = ManagedOAuthStorageService(args.storage_path)
    asyncio.run(cmd_show_limits(storage, args))


if __name__ == "__main__":
    main()
