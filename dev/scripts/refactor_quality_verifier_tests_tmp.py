from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

REPLACEMENTS = [
    ("tests.helpers.angel_factory_stub", "tests.helpers.quality_verifier_factory_stub"),
    ("AngelFactoryStub", "QualityVerifierFactoryStub"),
    ("DummyAngelFactory", "DummyQualityVerifierFactory"),
    ("test_response_processor_calls_angel_when_configured", "test_response_processor_calls_quality_verifier_when_configured"),
    ("test_apply_angel_verification", "test_apply_quality_verifier_verification"),
    ("_apply_angel_verification", "_apply_quality_verifier_verification"),
    ("parse_angel_output", "parse_quality_verifier_output"),
    ("validate_angel_output_format", "validate_quality_verifier_output_format"),
    ("get_prompt_loader", "get_quality_verifier_prompt_loader"),
    ("angel_prompt", "quality_verifier_prompt"),
    ("corrected_by_angel", "corrected_by_quality_verifier"),
    ("angel_decision", "quality_verifier_decision"),
    ("<angels_decision>", "<quality_verifier_decision>"),
    ("</angels_decision>", "</quality_verifier_decision>"),
    ("<angels_steering_message>", "<quality_verifier_steering_message>"),
    ("</angels_steering_message>", "</quality_verifier_steering_message>"),
    ("[Tool definitions omitted for Angel audit.]", "[Tool definitions omitted for Quality Verifier audit.]"),
    ("ANGEL", "QUALITY_VERIFIER"),
]


def apply(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    updated = text
    for old, new in REPLACEMENTS:
        updated = updated.replace(old, new)
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    changed = 0
    for path in TESTS.rglob("*.py"):
        if apply(path):
            changed += 1
    print(f"Updated {changed} test files")


if __name__ == "__main__":
    main()
