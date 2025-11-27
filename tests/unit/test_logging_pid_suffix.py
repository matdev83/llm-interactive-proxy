from src.core.cli import _apply_pid_suffixes
from src.core.config.app_config import AppConfig, LoggingConfig


def test_timestamp_suffix_applied_once() -> None:
    import re

    # Mock datetime to ensure consistent timestamp during test
    timestamp_pattern = re.compile(r"-\d{4}\.log$")

    cfg = AppConfig(
        logging=LoggingConfig(log_file="logs/proxy.log", capture_file="wire.log")
    )

    updated = _apply_pid_suffixes(cfg)
    assert timestamp_pattern.search(updated.logging.log_file)
    assert timestamp_pattern.search(updated.logging.capture_file)

    # Verify format is HHMM
    suffix = updated.logging.log_file[-8:-4]
    assert suffix.isdigit() and len(suffix) == 4

    updated_again = _apply_pid_suffixes(updated)
    assert updated_again.logging.log_file == updated.logging.log_file
    assert updated_again.logging.capture_file == updated.logging.capture_file
