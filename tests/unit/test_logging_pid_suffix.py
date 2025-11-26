import os

from src.core.cli import _apply_pid_suffixes
from src.core.config.app_config import AppConfig, LoggingConfig


def test_pid_suffix_applied_once() -> None:
    pid = os.getpid()
    cfg = AppConfig(
        logging=LoggingConfig(log_file="logs/proxy.log", capture_file="wire.log")
    )

    updated = _apply_pid_suffixes(cfg)
    assert updated.logging.log_file.endswith(f"-pid-{pid}.log")
    assert updated.logging.capture_file.endswith(f"-pid-{pid}.log")

    updated_again = _apply_pid_suffixes(updated)
    assert updated_again.logging.log_file == updated.logging.log_file
    assert updated_again.logging.capture_file == updated.logging.capture_file
