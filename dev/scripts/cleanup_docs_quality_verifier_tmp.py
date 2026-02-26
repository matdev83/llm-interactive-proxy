from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REPLACEMENTS = [
    ("features/angel-verification.md", "features/quality-verifier.md"),
    ("(angel-verification.md)", "(quality-verifier.md)"),
    ("../features/angel-verification.md", "../features/quality-verifier.md"),
    ("# Angel Verification System", "# Quality Verifier"),
    ("Angel Verification", "Quality Verifier"),
    ("Angel verification", "Quality Verifier"),
    ("Angel model", "Quality Verifier model"),
    ("ANGEL_MODEL", "QUALITY_VERIFIER_MODEL"),
    ("ANGEL_FREQUENCY", "QUALITY_VERIFIER_FREQUENCY"),
    ("ANGEL_MAX_HISTORY", "QUALITY_VERIFIER_MAX_HISTORY"),
    (
        "ANGEL_MAX_CONSECUTIVE_FAILURES",
        "QUALITY_VERIFIER_MAX_CONSECUTIVE_FAILURES",
    ),
    ("ANGEL_COOLDOWN_SECONDS", "QUALITY_VERIFIER_COOLDOWN_SECONDS"),
    ("--use-angel-model", "--quality-verifier-model"),
    ("--angel-frequency", "--quality-verifier-frequency"),
    ("--angel-max-history", "--quality-verifier-max-history"),
    (
        "--angel-max-consecutive-failures",
        "--quality-verifier-max-consecutive-failures",
    ),
    ("--angel-cooldown-seconds", "--quality-verifier-cooldown-seconds"),
    ("angel_model", "quality_verifier_model"),
    ("angel_frequency", "quality_verifier_frequency"),
    ("angel_max_history", "quality_verifier_max_history"),
    (
        "angel_max_consecutive_failures",
        "quality_verifier_max_consecutive_failures",
    ),
    ("angel_cooldown_seconds", "quality_verifier_cooldown_seconds"),
]


REMOVE_CONTAINS = [
    "llm-assessment.md",
    "LLM Assessment System",
    "--enable-llm-assessment",
    "--disable-llm-loop-assessment",
    "--llm-assessment-",
    "LLM_ASSESSMENT_",
    "### LLM Assessment",
    "assessment:",
    "llm_assessment:",
]


def process_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text
    for old, new in REPLACEMENTS:
        updated = updated.replace(old, new)

    if "docs/user_guide" in str(path).replace("\\", "/"):
        filtered_lines: list[str] = []
        for line in updated.splitlines():
            if any(token in line for token in REMOVE_CONTAINS):
                continue
            filtered_lines.append(line)
        updated = "\n".join(filtered_lines) + ("\n" if updated.endswith("\n") else "")

    if updated != text:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for base in [ROOT / "docs", ROOT / "config"]:
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            if process_file(path):
                changed += 1
        for path in base.rglob("*.yaml"):
            if process_file(path):
                changed += 1
        for path in base.rglob("*.yml"):
            if process_file(path):
                changed += 1
        for path in base.rglob("*.env"):
            if process_file(path):
                changed += 1
    print(f"Updated {changed} files")


if __name__ == "__main__":
    main()
