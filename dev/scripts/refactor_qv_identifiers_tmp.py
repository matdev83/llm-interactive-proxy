from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REPLACEMENTS = [
    ("AngelVerificationError", "QualityVerifierError"),
    ("class AngelConfig", "class QualityVerifierConfig"),
    ("_extract_angel_config", "_extract_quality_verifier_config"),
    ("_apply_angel_verification", "_apply_quality_verifier_verification"),
    ("_prepare_angel_extensions_for_backend_call", "_prepare_quality_verifier_extensions_for_backend_call"),
    ("_ensure_angel_not_cancelled", "_ensure_quality_verifier_not_cancelled"),
    ("_call_angel_once", "_call_quality_verifier_once"),
    ("suppress_replacement_for_angel", "suppress_replacement_for_quality_verifier"),
    ("angel_turn_incremented", "quality_verifier_turn_incremented"),
    ("angel_enabled", "quality_verifier_enabled"),
    ("angel_config", "quality_verifier_config"),
    ("angel_context", "quality_verifier_context"),
    ("angel_request", "quality_verifier_request"),
    ("angel_response", "quality_verifier_response"),
    ("angel_text", "quality_verifier_text"),
    ("MAX_ANGEL_BUFFER_BYTES", "MAX_QUALITY_VERIFIER_BUFFER_BYTES"),
    ("corrected_by_angel", "corrected_by_quality_verifier"),
    ("angel_decision", "quality_verifier_decision"),
    ("Angel stream verifier", "Quality Verifier stream verifier"),
    ("Angel service", "Quality Verifier service"),
    ("Angel verification", "Quality Verifier"),
    ("Angel correction", "Quality Verifier correction"),
    ("Angel model", "Quality Verifier model"),
]


def apply(path: Path) -> bool:
    try:
        original = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False

    updated = original
    for old, new in REPLACEMENTS:
        updated = updated.replace(old, new)

    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed = 0
    for path in (ROOT / "src").rglob("*.py"):
        if apply(path):
            changed += 1
    print(f"Updated {changed} files")


if __name__ == "__main__":
    main()
