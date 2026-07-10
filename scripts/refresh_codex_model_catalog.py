#!/usr/bin/env python3
"""Refresh the shipped Codex model catalog fallback snapshot.

Runs ``codex debug models`` via the resolved codex binary, validates the JSON,
and writes a normalized snapshot to ``src/resources/codex/codex_model_catalog.json``.
This snapshot is the fallback used by the ``openai-codex``, ``openai-codex-v2``
and ``openai-codex-app-server`` connectors when startup auto-discovery fails or
is disabled.

Usage::

    ./.venv/Scripts/python.exe scripts/refresh_codex_model_catalog.py
    ./.venv/Scripts/python.exe scripts/refresh_codex_model_catalog.py --output path/to/catalog.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.connectors.codex_helpers import candidate_codex_executables
from src.connectors.openai_codex.catalog.fallback_loader import (
    SHIPPED_RESOURCE_NAME,
    SHIPPED_RESOURCE_PACKAGE,
)

DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "resources" / "codex" / SHIPPED_RESOURCE_NAME
DEFAULT_TIMEOUT = 30.0


def _resolve_resource_dir() -> Path:
    package_dir = SHIPPED_RESOURCE_PACKAGE.replace(".", "/")
    return PROJECT_ROOT / package_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh the shipped Codex model catalog fallback snapshot."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--codex-binary",
        type=str,
        default=None,
        help="Explicit path to the codex binary (else resolved via PATH/CODEX_BIN).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Subprocess timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    args = parser.parse_args()

    candidates = candidate_codex_executables(args.codex_binary)
    if not candidates:
        print(
            "ERROR: codex executable not found. Install @openai/codex or set "
            "CODEX_BIN / --codex-binary.",
            file=sys.stderr,
        )
        return 2
    executable = candidates[0]

    try:
        result = subprocess.run(
            [executable, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"ERROR: `codex debug models` timed out after {args.timeout}s.",
            file=sys.stderr,
        )
        return 3
    if result.returncode != 0:
        print(
            f"ERROR: `codex debug models` exited with code {result.returncode}: "
            f"{(result.stderr or '').strip()}",
            file=sys.stderr,
        )
        return result.returncode

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(
            f"ERROR: `codex debug models` stdout is not valid JSON: {exc}",
            file=sys.stderr,
        )
        return 4

    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    models = data.get("models") if isinstance(data, dict) else None
    routable: list[str] = []
    for model in models or []:
        if not isinstance(model, dict):
            continue
        slug = model.get("slug")
        if not isinstance(slug, str):
            continue
        if (
            model.get("supported_in_api", True)
            and model.get("visibility", "list") != "hide"
        ):
            routable.append(slug)
    print(f"Wrote catalog snapshot to {output_path}")
    print(f"  models: {len(models or [])} total, {len(routable)} routable")
    print(f"  routable slugs: {', '.join(routable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
