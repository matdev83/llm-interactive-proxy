#!/usr/bin/env python3
"""Codemod to update imports for interface/service filename suffixes.

Replaces occurrences like:
  from src.core.interfaces.foo import Bar
with:
  from src.core.interfaces.foo_interface import Bar

and similarly for services -> *_service.

It auto-detects candidates from the filesystem.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def collect_candidates(dirpath: Path, suffix: str) -> dict[str, str]:
    mapping = {}
    if not dirpath.exists():
        return mapping
    for p in dirpath.iterdir():
        if p.is_file() and p.suffix == ".py":
            name = p.stem
            # skip already suffixed files and __init__
            if name.endswith(suffix) or name == "__init__":
                continue
            mapping[name] = f"{name}{suffix}"
    return mapping


def should_ignore(path: Path) -> bool:
    parts = set(path.parts)
    if ".venv" in parts or "venv" in parts or path.match("**/node_modules/**"):
        return True
    return False


def main() -> int:
    interfaces_dir = ROOT / "src" / "core" / "interfaces"
    services_dir = ROOT / "src" / "core" / "services"

    iface_map = collect_candidates(interfaces_dir, "_interface")
    svc_map = collect_candidates(services_dir, "_service")

    if not iface_map and not svc_map:
        # No candidates found -- nothing to modify
        return 0

    py_files = [p for p in ROOT.rglob("*.py") if not should_ignore(p)]

    modified = []

    # Precompile regexes for performance
    iface_patterns = [
        (re.compile(rf"from\s+src\.core\.interfaces\.{re.escape(k)}\b"), v)
        for k, v in iface_map.items()
    ]
    svc_patterns = [
        (re.compile(rf"from\s+src\.core\.services\.{re.escape(k)}\b"), v)
        for k, v in svc_map.items()
    ]

    # Also replace plain module references like "src.core.interfaces.foo"
    iface_dot_patterns = [
        (re.compile(rf"src\.core\.interfaces\.{re.escape(k)}\b"), v)
        for k, v in iface_map.items()
    ]
    svc_dot_patterns = [
        (re.compile(rf"src\.core\.services\.{re.escape(k)}\b"), v)
        for k, v in svc_map.items()
    ]

    for p in py_files:
        text = p.read_text(encoding="utf-8")
        new_text = text
        for rx, repl in iface_patterns:
            new_text = rx.sub(lambda m: m.group(0).replace(m.group(0).split()[1], f"src.core.interfaces.{repl}"), new_text)
        for rx, repl in svc_patterns:
            new_text = rx.sub(lambda m: m.group(0).replace(m.group(0).split()[1], f"src.core.services.{repl}"), new_text)

        # replace dotted references
        for rx, repl in iface_dot_patterns:
            new_text = rx.sub(f"src.core.interfaces.{repl}", new_text)
        for rx, repl in svc_dot_patterns:
            new_text = rx.sub(f"src.core.services.{repl}", new_text)

        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            modified.append(str(p.relative_to(ROOT)))

    # Use logging instead of print; tests forbid print() in repository files
    import logging

    logger = logging.getLogger("rename_imports")
    logger.info("Modified %d files", len(modified))
    for m in modified:
        logger.debug(m)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


