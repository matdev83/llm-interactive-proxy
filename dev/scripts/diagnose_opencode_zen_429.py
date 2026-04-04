"""Probe OpenCode Zen with varying HTTP versions, headers, and JSON bodies.

Helps isolate whether 429s come from HTTP/2, specific headers, or chat payload shape.

Usage (from repo root, with real auth.json on disk)::

    .\\.venv\\Scripts\\python.exe dev/scripts/diagnose_opencode_zen_429.py

Environment::

    OPENCODE_AUTH_PATH   Optional path to auth.json (else default OS locations)

Requires ``llm-interactive-proxy-oauth-connectors`` installed (editable) for credential normalization.
The probe bearer matches the connector: OAuth-style access fields, ``wellknown`` ``token``, or
OpenCode ``type=api`` ``key`` when no access-style field exists.

This script performs live calls to ``https://opencode.ai`` (or ``--base-url``).
By default it uses the free gateway model id ``minimax-m2.5-free`` (override with ``--model``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException


def _ensure_llm_interactive_proxy_src_importable() -> None:
    """``llm_proxy_oauth_connectors.opencode_zen`` imports ``src.*`` from the proxy package.

    Running this script from a git checkout does not put the repo root on ``sys.path`` by
    default; editable ``llm-interactive-proxy-oauth-connectors`` then fails with ``No module named src``.
    """

    here = Path(__file__).resolve()
    for ancestor in here.parents:
        if (ancestor / "src" / "connectors" / "openai.py").is_file():
            root = str(ancestor)
            if root not in sys.path:
                sys.path.insert(0, root)
            return


_ensure_llm_interactive_proxy_src_importable()

DEFAULT_BASE = "https://opencode.ai/zen/v1"
# Default Zen gateway id (free tier); override with --model if needed.
DEFAULT_ZEN_MODEL_ID = "minimax-m2.5-free"
ZEN_UA = "opencode/1.2.26 (llm-interactive-proxy; diagnose_opencode_zen_429)"


@dataclass
class Row:
    label: str
    http2: bool
    status: int
    body_preview: str
    ms: float


def _default_auth_paths() -> list[Path]:
    if sys.platform == "win32" or os.name == "nt":
        la = os.environ.get("LOCALAPPDATA")
        paths: list[Path] = []
        if la:
            paths.append(Path(la) / "opencode" / "auth.json")
        paths.append(Path.home() / ".local" / "share" / "opencode" / "auth.json")
        return paths
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return [Path(xdg) / "opencode" / "auth.json"]
    return [Path.home() / ".local" / "share" / "opencode" / "auth.json"]


def _resolve_auth_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    env = os.environ.get("OPENCODE_AUTH_PATH")
    if env:
        return Path(env).expanduser()
    for p in _default_auth_paths():
        if p.exists():
            return p
    raise FileNotFoundError(
        "No auth.json found. Set OPENCODE_AUTH_PATH or pass --auth-path."
    )


def _normalize_provider_fallback(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    if not (isinstance(out.get("access"), str) and out["access"].strip()):
        for alt in ("accessToken", "access_token", "token"):
            v = out.get(alt)
            if isinstance(v, str) and v.strip():
                out["access"] = v.strip()
                break
    return out


def load_bearer_token(auth_path: Path) -> tuple[str, str]:
    data = json.loads(auth_path.read_text(encoding="utf-8"))
    raw = data.get("opencode")
    if not isinstance(raw, dict):
        raise ValueError("auth.json: missing 'opencode' object")

    try:
        from llm_proxy_oauth_connectors import opencode_zen as _oz

        # Private helper; not part of the package typing surface.
        _normalize_opencode_provider_fields = getattr(
            _oz, "_normalize_opencode_provider_fields", None
        )
        if _normalize_opencode_provider_fields is None:
            prov = _normalize_provider_fallback(raw)
        else:
            prov = _normalize_opencode_provider_fields(raw)
    except ImportError:
        prov = _normalize_provider_fallback(raw)

    access = prov.get("access")
    if isinstance(access, str) and access.strip():
        return access.strip(), "oauth_access"
    raise ValueError(
        "auth.json: no Zen bearer material in opencode entry after normalization "
        "(access / accessToken / token / type=api key / …). Run `opencode auth login`."
    )


def header_variants() -> dict[str, dict[str, str]]:
    """Named outbound header sets to compare."""

    return {
        "H0_min": {
            "Authorization": "",  # filled later
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        "H1_zen_client": {
            "Authorization": "",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": ZEN_UA,
            "HTTP-Referer": "https://opencode.ai/",
            "X-Title": "opencode",
        },
        "H2_loop_guard": {
            "Authorization": "",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": ZEN_UA,
            "HTTP-Referer": "https://opencode.ai/",
            "X-Title": "opencode",
            "x-llmproxy-loop-guard": "1",
        },
        "H3_proxyish": {
            "Authorization": "",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "python-httpx/0.27.0",
            "X-Request-ID": "diag-429-test",
        },
    }


def body_variants(model: str) -> dict[str, dict[str, Any]]:
    base_msg = {"role": "user", "content": "Say only: ok"}

    return {
        "B0_nonstream_min": {
            "model": model,
            "messages": [base_msg],
            "stream": False,
            "max_tokens": 4,
        },
        "B1_stream_plain": {
            "model": model,
            "messages": [base_msg],
            "stream": True,
            "max_tokens": 4,
        },
        "B2_stream_options": {
            "model": model,
            "messages": [base_msg],
            "stream": True,
            "max_tokens": 4,
            "stream_options": {"include_usage": True},
        },
        "B3_extra_fields": {
            "model": model,
            "messages": [base_msg],
            "stream": False,
            "max_tokens": 4,
            "metadata": {"diag": "opencode-zen-429"},
            "parallel_tool_calls": False,
        },
    }


def _preview(text: str, limit: int = 160) -> str:
    t = text.replace("\n", "\\n")
    return t if len(t) <= limit else t[: limit - 3] + "..."


def _denormalize_model_for_zen(model_id: str) -> str:
    """Strip vendor/ prefix for Zen raw id (same idea as connector)."""

    if "/" in model_id:
        return model_id.split("/")[-1]
    return model_id


async def probe_post(
    *,
    client: httpx.AsyncClient,
    base: str,
    label: str,
    http2: bool,
    headers: dict[str, str],
    body: dict[str, Any],
) -> Row:
    url = f"{base.rstrip('/')}/chat/completions"
    t0 = time.perf_counter()
    try:
        r = await client.post(url, headers=headers, json=body, timeout=60.0)
        ms = (time.perf_counter() - t0) * 1000
        try:
            preview = _preview(r.text)
        except (UnicodeDecodeError, TypeError):
            preview = "<non-text body>"
        return Row(
            label=label, http2=http2, status=r.status_code, body_preview=preview, ms=ms
        )
    except httpx.HTTPError as e:
        ms = (time.perf_counter() - t0) * 1000
        return Row(
            label=label,
            http2=http2,
            status=-1,
            body_preview=_preview(str(e)),
            ms=ms,
        )


async def run_raw_matrix(
    *,
    base: str,
    bearer: str,
    model: str,
    quick: bool,
) -> list[Row]:
    hsets = header_variants()
    bsets = body_variants(model)
    if quick:
        hsets = {k: v for k, v in hsets.items() if k in ("H0_min", "H1_zen_client")}
        bsets = {
            k: v
            for k, v in bsets.items()
            if k in ("B0_nonstream_min", "B2_stream_options")
        }

    rows: list[Row] = []
    for http2 in (False, True):
        transport_label = "h2" if http2 else "h11"
        async with httpx.AsyncClient(
            http2=http2, timeout=60.0, trust_env=False
        ) as client:
            for hk, hd in hsets.items():
                headers = {**hd, "Authorization": f"Bearer {bearer}"}
                for bk, body in bsets.items():
                    label = f"{transport_label}/{hk}/{bk}"
                    rows.append(
                        await probe_post(
                            client=client,
                            base=base,
                            label=label,
                            http2=http2,
                            headers=headers,
                            body=dict(body),
                        )
                    )
    return rows


async def run_connector_smoke(
    *,
    auth_path: Path,
    base: str,
    logical_model: str,
) -> Row:
    """One non-stream request through OpencodeZenConnector (full proxy stack)."""

    from llm_proxy_oauth_connectors.opencode_zen import OpencodeZenConnector
    from src.core.config.app_config import AppConfig
    from src.core.domain.chat import ChatMessage, ChatRequest
    from src.core.services.translation_service import TranslationService

    shared = httpx.AsyncClient(http2=True, timeout=60.0, trust_env=False)
    conn = None
    try:
        conn = OpencodeZenConnector(shared, AppConfig(), TranslationService())
        await conn.initialize(
            credentials_path=str(auth_path),
            api_base_url=base,
            enable_opencode_zen_backend_debugging_override=True,
        )
        if not conn.is_functional:
            return Row(
                label="connector/init_failed",
                http2=True,
                status=-2,
                body_preview="connector not functional after initialize",
                ms=0.0,
            )

        prefixed = f"opencode-zen:{logical_model}"
        req = ChatRequest(
            model=prefixed,
            messages=[ChatMessage(role="user", content="Say only: ok")],
            stream=False,
            max_tokens=8,
        )
        t0 = time.perf_counter()
        try:
            resp = await conn.chat_completions(req, list(req.messages), prefixed)
            ms = (time.perf_counter() - t0) * 1000
            st = int(getattr(resp, "status_code", 200))
            body = getattr(resp, "content", "")
            if isinstance(body, Mapping):
                prev = _preview(json.dumps(body)[:300])
            else:
                prev = _preview(str(body))
            return Row(
                label="connector/chat_completions(non-stream)",
                http2=True,
                status=st,
                body_preview=prev,
                ms=ms,
            )
        except HTTPException as e:
            ms = (time.perf_counter() - t0) * 1000
            return Row(
                label="connector/chat_completions(non-stream)",
                http2=True,
                status=int(e.status_code),
                body_preview=_preview(repr(e.detail)),
                ms=ms,
            )
        except Exception as e:
            ms = (time.perf_counter() - t0) * 1000
            return Row(
                label="connector/chat_completions(non-stream)",
                http2=True,
                status=-1,
                body_preview=_preview(repr(e)),
                ms=ms,
            )
    finally:
        if conn is not None:
            await conn.close()
        await shared.aclose()


def print_table(rows: list[Row]) -> None:
    print(f"{'label':<48} {'h2':>4} {'sts':>5} {'ms':>8}  body")
    print("-" * 120)
    for r in rows:
        print(
            f"{r.label:<48} {r.http2!s:>4} {r.status:>5} {r.ms:>8.1f}  {r.body_preview}"
        )


def _print_interpretation(rows: list[Row]) -> None:
    """Explain common uniform outcomes (stderr)."""

    if not rows:
        return
    completed = [r for r in rows if r.status >= 0]
    if not completed:
        return
    if not all(r.status == 429 for r in completed):
        return
    if not all("FreeUsageLimitError" in r.body_preview for r in completed):
        print(
            "\nInterpretation: All probes returned HTTP 429, but the response body did "
            "not consistently include `FreeUsageLimitError`. Inspect bodies above or "
            "compare with Zen/OpenCode status pages.",
            file=sys.stderr,
        )
        return

    print(
        "\nInterpretation: Every completed probe returned HTTP 429 with Zen's "
        "`FreeUsageLimitError` (free usage / quota for this credential). "
        "This is not explained by HTTP/1.1 vs HTTP/2, headers, or chat JSON shape — "
        "those dimensions were varied and the error stayed identical. Wait for quota to "
        "reset, use another account, or switch to credentials with remaining free tier.",
        file=sys.stderr,
    )


async def _async_main(args: argparse.Namespace) -> int:
    auth_path = _resolve_auth_path(Path(args.auth_path) if args.auth_path else None)
    bearer, kind = load_bearer_token(auth_path)
    print(f"auth.json: {auth_path}", file=sys.stderr)
    print(f"bearer: <{kind}, len={len(bearer)}>", file=sys.stderr)

    base = args.base_url.rstrip("/")

    logical_model = args.model
    zen_body_model = _denormalize_model_for_zen(logical_model)
    print(
        f"Zen model id: {logical_model!r} (POST body `model`: {zen_body_model!r})",
        file=sys.stderr,
    )
    print(
        f"Connector request model: opencode-zen:{logical_model}",
        file=sys.stderr,
    )

    rows: list[Row] = []

    if args.probe in ("raw", "both"):
        rows.extend(
            await run_raw_matrix(
                base=base,
                bearer=bearer,
                model=zen_body_model,
                quick=args.quick,
            )
        )

    if args.probe in ("connector", "both"):
        rows.append(
            await run_connector_smoke(
                auth_path=auth_path,
                base=base,
                logical_model=logical_model,
            )
        )

    print_table(rows)

    _print_interpretation(rows)

    bad = [r for r in rows if r.status not in (200,) and r.status != -2]
    if any(r.status == 429 for r in rows):
        if not (
            bad
            and all(r.status == 429 for r in bad)
            and all("FreeUsageLimitError" in r.body_preview for r in bad)
        ):
            print(
                "\nSummary: at least one HTTP 429 — if error types differ across rows, "
                "compare rows that change only one dimension.",
                file=sys.stderr,
            )
    elif bad:
        print(
            f"\nSummary: {len(bad)} non-200 responses (excluding init failures).",
            file=sys.stderr,
        )
    else:
        print("\nSummary: all probes returned HTTP 200.", file=sys.stderr)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--auth-path",
        type=str,
        default=None,
        help="Path to opencode auth.json (default: OPENCODE_AUTH_PATH or OS default)",
    )
    p.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE,
        help=f"Zen OpenAI base (default {DEFAULT_BASE})",
    )
    p.add_argument(
        "--model",
        type=str,
        default=DEFAULT_ZEN_MODEL_ID,
        help=f"Zen chat `model` id (default: {DEFAULT_ZEN_MODEL_ID!r}, free tier)",
    )
    p.add_argument(
        "--probe",
        choices=("raw", "connector", "both"),
        default="raw",
        help="raw=httpx matrix; connector=OpencodeZenConnector one-shot; both",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="Smaller raw matrix (2 header x 2 body x 2 HTTP versions)",
    )
    args = p.parse_args()
    try:
        return asyncio.run(_async_main(args))
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
