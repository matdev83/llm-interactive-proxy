import argparse
import os
import logging
import uvicorn
from typing import Any, Dict

from src.core.config import _load_config
from src.main import build_app # Temporarily import from src.main

def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LLM proxy server")
    parser.add_argument(
        "--default-backend",
        dest="default_backend",
        choices=["openrouter", "gemini"],
        default=os.getenv("LLM_BACKEND"),
        help="Default backend when multiple backends are functional",
    )
    parser.add_argument(
        "--backend",
        dest="default_backend",
        choices=["openrouter", "gemini"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-api-base-url")
    parser.add_argument("--gemini-api-key")
    parser.add_argument("--gemini-api-base-url")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--command-prefix")
    parser.add_argument(
        "--interactive-mode",
        action="store_true",
        default=None,
        help="Enable interactive mode by default for new sessions",
    )
    return parser.parse_args(argv)


def apply_cli_args(args: argparse.Namespace) -> Dict[str, Any]:
    mappings = {
        "default_backend": "LLM_BACKEND",
        "openrouter_api_key": "OPENROUTER_API_KEY",
        "openrouter_api_base_url": "OPENROUTER_API_BASE_URL",
        "gemini_api_key": "GEMINI_API_KEY",
        "gemini_api_base_url": "GEMINI_API_BASE_URL",
        "host": "PROXY_HOST",
        "port": "PROXY_PORT",
        "timeout": "PROXY_TIMEOUT",
        "command_prefix": "COMMAND_PREFIX",
        "interactive_mode": "INTERACTIVE_MODE",
    }
    for attr, env_name in mappings.items():
        value = getattr(args, attr)
        if value is not None:
            os.environ[env_name] = str(value)
    return _load_config()


def main(argv: list[str] | None = None) -> None:
    args = parse_cli_args(argv)
    cfg = apply_cli_args(args)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    app = build_app(cfg)
    uvicorn.run(app, host=cfg["proxy_host"], port=cfg["proxy_port"])
