from __future__ import annotations

from src.core.cli import parse_cli_args
from src.core.config.app_config import AppConfig


def main() -> None:
    args = parse_cli_args([])
    print(f"command_prefix_arg={getattr(args, 'command_prefix', None)!r}")
    cfg = AppConfig()
    print(f"default cfg.command_prefix={cfg.command_prefix!r}")


if __name__ == "__main__":
    main()

