#!/usr/bin/env python3
"""
Demo script: Generate a simple OS notification using desktop-notifier.

Usage:
    ./.venv/Scripts/python.exe scripts/demo_notification.py

This demonstrates the desktop-notifier package sending a native OS notification.
"""

import asyncio
from desktop_notifier import DesktopNotifier


async def main():
    notifier = DesktopNotifier()

    notification_id = await notifier.send(
        title="LLM Interactive Proxy",
        message="Notification system is working!",
    )

    print(f"Notification sent: ID={notification_id}")
    print("Check your OS notification area for the message.")


if __name__ == "__main__":
    asyncio.run(main())
