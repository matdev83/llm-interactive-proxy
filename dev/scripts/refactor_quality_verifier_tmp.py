from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


RENAMES = [
    (
        "src/core/services/backend_request_manager/angel_stream_verifier.py",
        "src/core/services/backend_request_manager/quality_verifier_stream_verifier.py",
    ),
    ("src/core/services/angel_service.py", "src/core/services/quality_verifier_service.py"),
    (
        "src/core/services/angel_prompt_loader.py",
        "src/core/services/quality_verifier_prompt_loader.py",
    ),
    (
        "src/core/services/angel_service_factory.py",
        "src/core/services/quality_verifier_service_factory.py",
    ),
    (
        "src/core/interfaces/angel_service_interface.py",
        "src/core/interfaces/quality_verifier_service_interface.py",
    ),
    ("src/core/domain/angel.py", "src/core/domain/quality_verifier.py"),
    (
        "tests/unit/core/services/test_angel_stream_verifier.py",
        "tests/unit/core/services/test_quality_verifier_stream_verifier.py",
    ),
    (
        "tests/unit/core/services/test_angel_service.py",
        "tests/unit/core/services/test_quality_verifier_service.py",
    ),
    (
        "tests/unit/core/services/test_angel_circuit_breaker.py",
        "tests/unit/core/services/test_quality_verifier_circuit_breaker.py",
    ),
    (
        "tests/unit/core/services/test_backend_request_manager_angel.py",
        "tests/unit/core/services/test_backend_request_manager_quality_verifier.py",
    ),
    (
        "tests/unit/core/services/test_response_processor_angel.py",
        "tests/unit/core/services/test_response_processor_quality_verifier.py",
    ),
    (
        "tests/unit/core/domain/test_model_utils_angel.py",
        "tests/unit/core/domain/test_model_utils_quality_verifier.py",
    ),
    (
        "tests/regression/test_angel_service_race_condition.py",
        "tests/regression/test_quality_verifier_service_race_condition.py",
    ),
    (
        "tests/integration/test_angel_integration.py",
        "tests/integration/test_quality_verifier_integration.py",
    ),
    (
        "tests/behavior/test_angel_behavior.py",
        "tests/behavior/test_quality_verifier_behavior.py",
    ),
    ("tests/helpers/angel_factory_stub.py", "tests/helpers/quality_verifier_factory_stub.py"),
    ("tests/unit/test_angel_config.py", "tests/unit/test_quality_verifier_config.py"),
    (
        "docs/user_guide/features/angel-verification.md",
        "docs/user_guide/features/quality-verifier.md",
    ),
    (
        "config/prompts/angel_prompts/angel_prompt.md",
        "config/prompts/angel_prompts/quality_verifier_prompt.md",
    ),
]


DIR_RENAMES = [
    ("config/prompts/angel_prompts", "config/prompts/quality_verifier_prompts"),
]


REPLACEMENTS = [
    ("IAngelServiceFactory", "IQualityVerifierServiceFactory"),
    ("DefaultAngelServiceFactory", "DefaultQualityVerifierServiceFactory"),
    ("AngelStreamVerifier", "QualityVerifierStreamVerifier"),
    ("IAngelStreamVerifier", "IQualityVerifierStreamVerifier"),
    ("AngelPromptLoader", "QualityVerifierPromptLoader"),
    ("AngelPromptInfo", "QualityVerifierPromptInfo"),
    ("AngelVerificationRequest", "QualityVerifierRequest"),
    ("AngelVerificationResult", "QualityVerifierResult"),
    ("AngelDecision", "QualityVerifierDecision"),
    ("AngelService", "QualityVerifierService"),
    ("angel_prompt.md", "quality_verifier_prompt.md"),
    ("angel_prompts", "quality_verifier_prompts"),
    ("angel_service", "quality_verifier_service"),
    ("angel_prompt_loader", "quality_verifier_prompt_loader"),
    ("angel_service_factory", "quality_verifier_service_factory"),
    ("angel_stream_verifier", "quality_verifier_stream_verifier"),
    ("test_angel_", "test_quality_verifier_"),
    ("use_angel_model", "quality_verifier_model"),
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
    ("angel_eligible_turn_count", "quality_verifier_eligible_turn_count"),
    ("angel_skip_verification", "quality_verifier_skip_verification"),
    (
        "replacement_suppressed_for_angel",
        "replacement_suppressed_for_quality_verifier",
    ),
    ("ANGEL_MODEL", "QUALITY_VERIFIER_MODEL"),
    ("ANGEL_FREQUENCY", "QUALITY_VERIFIER_FREQUENCY"),
    ("ANGEL_MAX_HISTORY", "QUALITY_VERIFIER_MAX_HISTORY"),
    (
        "ANGEL_MAX_CONSECUTIVE_FAILURES",
        "QUALITY_VERIFIER_MAX_CONSECUTIVE_FAILURES",
    ),
    ("ANGEL_COOLDOWN_SECONDS", "QUALITY_VERIFIER_COOLDOWN_SECONDS"),
    ("<override_angel>", "<override_quality_verifier>"),
    ("</override_angel>", "</override_quality_verifier>"),
    ("<override_angel", "<override_quality_verifier"),
    ("override_angel", "override_quality_verifier"),
    ("invalid_angel_reply", "invalid_quality_verifier_reply"),
    ("ANGEL STEERING", "QUALITY VERIFIER STEERING"),
    ("angel_steering", "quality_verifier_steering"),
    ("Angel Verification", "Quality Verifier"),
    ("Angel verification", "Quality Verifier"),
    ("Angel model", "Quality Verifier model"),
]


TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
    ".env",
    ".toml",
    ".schema",
    ".patch",
}


TARGET_DIRS = ["src", "tests", "docs", "config"]


def rename_paths() -> None:
    for src_rel, dst_rel in RENAMES:
        src = ROOT / src_rel
        dst = ROOT / dst_rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)

    for src_rel, dst_rel in DIR_RENAMES:
        src = ROOT / src_rel
        dst = ROOT / dst_rel
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            src.rename(dst)


def rewrite_text() -> int:
    changed = 0
    for root_rel in TARGET_DIRS:
        root = ROOT / root_rel
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in TEXT_SUFFIXES:
                continue
            try:
                original = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue

            updated = original
            for old, new in REPLACEMENTS:
                updated = updated.replace(old, new)

            if updated != original:
                path.write_text(updated, encoding="utf-8")
                changed += 1
    return changed


def main() -> None:
    rename_paths()
    changed = rewrite_text()
    print(f"Updated {changed} files")


if __name__ == "__main__":
    main()
