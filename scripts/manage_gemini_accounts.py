#!/usr/bin/env python3
"""
Management script for Gemini OAuth Auto-Connector accounts.

Provides commands to list, add, update, and remove Google accounts
used for Gemini API authentication.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to sys.path to allow imports from the project
sys.path.append(str(Path(__file__).parent.parent))

from src.connectors.gemini_oauth_auto.constants import DEFAULT_STORAGE_PATH
from src.connectors.gemini_oauth_auto.errors import OAuthError
from src.connectors.gemini_oauth_auto.oauth_flow import OAuthFlowService
from src.connectors.gemini_oauth_auto.token_storage import TokenStorageService

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def cmd_list(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """List all registered accounts."""
    summaries = await storage.list_accounts()

    if not summaries:
        print("No accounts registered.")
        print("Use 'add' command to register a new account.")
        return

    if args.json:
        print(json.dumps([s.model_dump() for s in summaries], indent=2))
        return

    # Print table header
    header = f"{'Account ID':<20} {'Email':<30} {'Status':<15} {'Last Used':<25}"
    print(header)
    print("-" * len(header))

    for s in summaries:
        last_used = s.last_used or "Never"
        print(f"{s.account_id:<20} {s.email:<30} {s.status:<15} {last_used:<25}")


async def cmd_add(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Add a new Google account."""
    flow = OAuthFlowService(storage=storage)
    try:
        account = await flow.authorize(
            account_id=args.account_id,
            port=args.port,
            timeout=args.timeout,
            open_browser=not args.no_browser,
        )
        print(f"\nSuccessfully added account: {account.account_id} ({account.email})")
    except OAuthError as e:
        print(f"\nError: {e}")
        sys.exit(1)


async def cmd_update(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Update (re-authorize) an existing account."""
    account = await storage.get_account(args.account_id)
    if not account:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)

    flow = OAuthFlowService(storage=storage)
    try:
        updated = await flow.authorize(
            account_id=args.account_id,
            port=args.port,
            timeout=args.timeout,
            open_browser=not args.no_browser,
        )
        print(f"\nSuccessfully updated account: {updated.account_id} ({updated.email})")
    except OAuthError as e:
        print(f"\nError: {e}")
        sys.exit(1)


async def cmd_remove(storage: TokenStorageService, args: argparse.Namespace) -> None:
    """Remove a registered account."""
    if not args.force:
        confirm = input(
            f"Are you sure you want to remove account '{args.account_id}'? [y/N] "
        )
        if confirm.lower() != "y":
            print("Aborted.")
            return

    deleted = await storage.delete_account(args.account_id)
    if deleted:
        print(f"Removed account: {args.account_id}")
        print("\nNote: This only removes the local credentials file.")
        print(
            "You may also want to revoke access in your Google Account security settings:"
        )
        print("https://myaccount.google.com/permissions")
    else:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)


async def cmd_show(storage: TokenStorageService, args: argparse.Namespace) -> None:
    account = await storage.get_account(args.account_id)
    if not account:
        print(f"Error: Account '{args.account_id}' not found.")
        sys.exit(1)

    if args.json:
        print(account.model_dump_json(indent=2))
        return

    print(f"Account Details: {account.account_id}")
    print("-" * 40)
    print(f"Email:         {account.email}")
    print(f"Status:        {account.status}")
    print(f"Created At:    {account.created_at}")
    print(f"Updated At:    {account.updated_at}")
    print(f"Last Used:     {account.last_used or 'Never'}")
    print(
        f"Expiry Date:   {account.expiry_date} ({datetime.fromtimestamp(account.expiry_date / 1000, tz=timezone.utc).isoformat()})"
    )
    print(f"Needs Reauth:  {account.needs_reauth}")
    print(f"Scopes:        {account.scope}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Gemini OAuth accounts")
    parser.add_argument(
        "--storage-path",
        default=DEFAULT_STORAGE_PATH,
        help=f"Path to storage directory (default: {DEFAULT_STORAGE_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.required = True

    # List command
    list_parser = subparsers.add_parser("list", help="List registered accounts")
    list_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    show_parser = subparsers.add_parser(
        "show", help="Show detailed account information"
    )
    show_parser.add_argument("account_id", help="Identifier of the account to show")
    show_parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new Google account")
    add_parser.add_argument("--account-id", help="Custom identifier for this account")
    add_parser.add_argument("--port", type=int, help="Fixed port for callback server")
    add_parser.add_argument(
        "--timeout", type=int, default=120, help="Authorization timeout in seconds"
    )
    add_parser.add_argument(
        "--no-browser", action="store_true", help="Do not auto-open browser"
    )

    # Update command
    update_parser = subparsers.add_parser(
        "update", help="Update (re-authorize) an existing account"
    )
    update_parser.add_argument("account_id", help="Identifier of the account to update")
    update_parser.add_argument(
        "--port", type=int, help="Fixed port for callback server"
    )
    update_parser.add_argument(
        "--timeout", type=int, default=120, help="Authorization timeout in seconds"
    )
    update_parser.add_argument(
        "--no-browser", action="store_true", help="Do not auto-open browser"
    )

    # Remove command
    remove_parser = subparsers.add_parser("remove", help="Remove a registered account")
    remove_parser.add_argument("account_id", help="Identifier of the account to remove")
    remove_parser.add_argument(
        "--force", action="store_true", help="Skip confirmation prompt"
    )

    args = parser.parse_args()
    storage = TokenStorageService(storage_path=args.storage_path)

    if args.command == "list":
        asyncio.run(cmd_list(storage, args))
    elif args.command == "show":
        asyncio.run(cmd_show(storage, args))
    elif args.command == "add":
        asyncio.run(cmd_add(storage, args))
    elif args.command == "update":
        asyncio.run(cmd_update(storage, args))
    elif args.command == "remove":
        asyncio.run(cmd_remove(storage, args))


if __name__ == "__main__":
    main()
