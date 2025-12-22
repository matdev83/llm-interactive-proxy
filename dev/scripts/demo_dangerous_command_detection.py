"""
Quick demo for dangerous command detection.

Run:
    ./.venv/Scripts/python.exe scripts/demo_dangerous_command_detection.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.di.container import ServiceCollection
from src.core.services.dangerous_command_service import (
    DangerousCommandService,
)


def main() -> None:
    services = ServiceCollection()
    provider = services.build_service_provider()
    service = provider.get_required_service(DangerousCommandService)

    demo_commands = [
        "git checkout -- .",
        "git    checkout   --   .",
        "git \\ checkout -- .",
        "git checkout .",
        "git checkout -- src/main.py",
        "git --work-tree=. checkout -- .",
        "GIT --WORK-TREE=. CHECKOUT -- .",
        "git --some-option checkout -- .",
        "git checkout --orphan new-branch",
        "rm -rf .",
        "find . -type f -exec rm -rf {} \\;",
        "rmdir /s /q C:\\\\temp",
        "powershell Remove-Item C:\\\\logs\\* -Recurse -Force",
    ]

    print("Demo payload (tool call) shape:")
    print(
        {
            "tool_name": "Execute",
            "arguments": {"command": "git checkout -- ."},
        }
    )
    print()

    print("Detection results:")
    for cmd in demo_commands:
        result = service.scan("Execute", {"command": cmd})
        status = "BLOCKED" if result else "allowed"
        print(f"{cmd!r:40} -> {status}")


if __name__ == "__main__":
    main()
