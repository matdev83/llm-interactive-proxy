"""Vercel Eve backend connector using native Agent Client Protocol (ACP) over stdio NDJSON."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from src.connectors.acp_core.acp_subprocess_identity import (
    capture_acp_subprocess_identity,
)
from src.connectors.acp_core.base_connector import BaseAcpConnector
from src.connectors.acp_core.transcript import ACPTranscriptSerializer
from src.connectors.acp_core.types import ACPNotification, ACPProcessRuntime
from src.connectors.acp_core.workspace_policy import resolve_backend_init_acp_workspace
from src.connectors.base import add_vendor_prefix, strip_vendor_prefix
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.core.common.exceptions import BackendError, ConfigurationError
from src.core.common.model_catalog import BackendModelEnumeration
from src.core.config.app_config import AppConfig, BackendConfig
from src.core.services.translation_service import TranslationService

logger = logging.getLogger(__name__)

ACP_PROTOCOL_VERSION = 1
DEFAULT_EVE_MODEL = "zai/glm-5.2"
DEFAULT_EVE_PROCESS_TIMEOUT_SECONDS = 600.0
DEFAULT_EVE_IDLE_TIMEOUT_SECONDS = 180.0
# Keep the serialized ACP request below the body-size limits commonly applied
# by Eve's local Nitro server and its upstream model gateway. Eve's own
# compactor runs after this request has been accepted, so it cannot protect an
# oversized first ``session/prompt`` body.
DEFAULT_EVE_MAX_PROMPT_BYTES = 450_000
EVE_RUNTIME_DIRECTORY_PREFIX = "acp-runtime-"


def canonicalize_eve_model_id(native_id: str) -> str:
    """Normalize model string to canonical Eve model ID."""
    model = native_id.strip()
    if not model or model == "auto":
        return DEFAULT_EVE_MODEL
    if model.startswith("eve/"):
        model = model[4:].strip()
    if model in ("glm-5.2", "glm5.2"):
        return "zai/glm-5.2"
    return model


DEFAULT_EVE_AGENT_NAME = "eve-acp-wrapper-agent"
DEFAULT_EVE_AGENT_PATH = Path.home() / ".eve" / "agents" / DEFAULT_EVE_AGENT_NAME

STANDARD_EVE_TOOLS: dict[str, str] = {
    "ask_question.ts": (
        'import { disableTool } from "eve/tools";\n\n' "export default disableTool();\n"
    ),
    "read_file.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n'
        'import * as fs from "node:fs/promises";\n'
        'import * as path from "node:path";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Read a text file from the local host filesystem. Supports optional startLine and endLine (1-indexed).",\n'
        "  inputSchema: z.object({\n"
        '    path: z.string().describe("Path to the file on the host filesystem (absolute or relative)."),\n'
        '    startLine: z.number().optional().describe("Optional 1-based start line number (inclusive)."),\n'
        '    endLine: z.number().optional().describe("Optional 1-based end line number (inclusive)."),\n'
        "  }),\n"
        "  async execute({ path: filePath, startLine, endLine }) {\n"
        "    try {\n"
        "      const baseDir = process.env.EVE_TARGET_WORKSPACE || process.cwd();\n"
        "      const resolved = path.isAbsolute(filePath) ? filePath : path.resolve(baseDir, filePath);\n"
        '      const content = await fs.readFile(resolved, "utf-8");\n'
        "      const lines = content.split(/\\r?\\n/);\n"
        "      const start = startLine && startLine > 0 ? startLine - 1 : 0;\n"
        "      const end = endLine && endLine > 0 ? Math.min(endLine, lines.length) : lines.length;\n"
        "      const selected = lines.slice(start, end);\n"
        "      const numbered = selected.map((line, idx) => `${start + idx + 1}: ${line}`).join('\\n');\n"
        "      await pace();\n"
        "      return { path: resolved, totalLines: lines.length, content: numbered };\n"
        "    } catch (err: any) {\n"
        "      await pace();\n"
        "      return { error: `Failed to read file: ${err.message || String(err)}` };\n"
        "    }\n"
        "  },\n"
        "});\n"
    ),
    "write_file.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n'
        'import * as fs from "node:fs/promises";\n'
        'import * as path from "node:path";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Write or overwrite a file on the local host filesystem. Automatically creates parent directories.",\n'
        "  inputSchema: z.object({\n"
        '    path: z.string().describe("Path to the file on the host filesystem (absolute or relative)."),\n'
        '    content: z.string().describe("Full text content to write to the file."),\n'
        "  }),\n"
        "  async execute({ path: filePath, content }) {\n"
        "    try {\n"
        "      const baseDir = process.env.EVE_TARGET_WORKSPACE || process.cwd();\n"
        "      const resolved = path.isAbsolute(filePath) ? filePath : path.resolve(baseDir, filePath);\n"
        "      await fs.mkdir(path.dirname(resolved), { recursive: true });\n"
        '      await fs.writeFile(resolved, content, "utf-8");\n'
        "      await pace();\n"
        '      return { success: true, path: resolved, bytesWritten: Buffer.byteLength(content, "utf-8") };\n'
        "    } catch (err: any) {\n"
        "      await pace();\n"
        "      return { error: `Failed to write file: ${err.message || String(err)}` };\n"
        "    }\n"
        "  },\n"
        "});\n"
    ),
    "bash.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n'
        'import * as child_process from "node:child_process";\n'
        'import * as path from "node:path";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Execute a shell command directly on the host machine. On Windows, runs PowerShell / cmd in the workspace.",\n'
        "  inputSchema: z.object({\n"
        '    command: z.string().describe("The shell command to execute."),\n'
        '    cwd: z.string().optional().describe("Optional working directory on the host filesystem."),\n'
        '    timeoutMs: z.number().optional().describe("Optional timeout in milliseconds (default: 120000)."),\n'
        "  }),\n"
        "  async execute({ command, cwd, timeoutMs = 120000 }) {\n"
        "    return new Promise((resolve) => {\n"
        "      const baseDir = process.env.EVE_TARGET_WORKSPACE || process.cwd();\n"
        "      const effectiveCwd = cwd ? (path.isAbsolute(cwd) ? cwd : path.resolve(baseDir, cwd)) : baseDir;\n"
        '      const isWindows = process.platform === "win32";\n'
        '      const shell = isWindows ? "powershell.exe" : "/bin/bash";\n'
        '      const args = isWindows ? ["-NoProfile", "-NonInteractive", "-Command", command] : ["-c", command];\n\n'
        "      const proc = child_process.spawn(shell, args, {\n"
        "        cwd: effectiveCwd,\n"
        "        windowsHide: true,\n"
        "        env: { ...process.env },\n"
        "      });\n\n"
        '      let stdout = "";\n'
        '      let stderr = "";\n\n'
        '      proc.stdout.on("data", (data) => {\n'
        '        stdout += data.toString("utf-8");\n'
        "      });\n"
        '      proc.stderr.on("data", (data) => {\n'
        '        stderr += data.toString("utf-8");\n'
        "      });\n\n"
        "      const timer = setTimeout(async () => {\n"
        "        try { proc.kill(); } catch (_) {}\n"
        "        await pace();\n"
        "        resolve({\n"
        "          stdout: stdout.slice(-30000),\n"
        '          stderr: stderr.slice(-30000) + "\\n[Command timed out]",\n'
        "          exitCode: 124,\n"
        "          cwd: effectiveCwd,\n"
        "        });\n"
        "      }, timeoutMs);\n\n"
        '      proc.on("close", async (code) => {\n'
        "        clearTimeout(timer);\n"
        "        await pace();\n"
        "        resolve({\n"
        "          stdout: stdout.slice(-50000),\n"
        "          stderr: stderr.slice(-50000),\n"
        "          exitCode: code ?? 0,\n"
        "          cwd: effectiveCwd,\n"
        "        });\n"
        "      });\n\n"
        '      proc.on("error", async (err) => {\n'
        "        clearTimeout(timer);\n"
        "        await pace();\n"
        "        resolve({\n"
        "          stdout,\n"
        "          stderr: `Spawn error: ${err.message}`,\n"
        "          exitCode: 1,\n"
        "          cwd: effectiveCwd,\n"
        "        });\n"
        "      });\n"
        "    });\n"
        "  },\n"
        "});\n"
    ),
    "glob.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n'
        'import * as fs from "node:fs/promises";\n'
        'import * as path from "node:path";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "async function walkDir(dir: string, pattern: RegExp, maxResults = 100): Promise<string[]> {\n"
        "  const results: string[] = [];\n"
        "  async function recurse(current: string) {\n"
        "    if (results.length >= maxResults) return;\n"
        "    try {\n"
        "      const entries = await fs.readdir(current, { withFileTypes: true });\n"
        "      for (const entry of entries) {\n"
        "        if (results.length >= maxResults) return;\n"
        '        if (entry.name === ".git" || entry.name === "node_modules" || entry.name === ".venv") continue;\n'
        "        const full = path.join(current, entry.name);\n"
        "        if (entry.isDirectory()) {\n"
        "          await recurse(full);\n"
        '        } else if (pattern.test(full.replace(/\\\\/g, "/")) || pattern.test(entry.name)) {\n'
        "          results.push(full);\n"
        "        }\n"
        "      }\n"
        "    } catch (_) {}\n"
        "  }\n"
        "  await recurse(dir);\n"
        "  return results;\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Find files by pattern on the host filesystem.",\n'
        "  inputSchema: z.object({\n"
        "    pattern: z.string().describe(\"Search pattern or file name/extension (e.g. '*.py', 'test_*', 'package.json').\"),\n"
        '    path: z.string().optional().describe("Directory to start search from (default: current workspace)."),\n'
        "  }),\n"
        "  async execute({ pattern, path: startDir }) {\n"
        "    try {\n"
        "      const baseDir = process.env.EVE_TARGET_WORKSPACE || process.cwd();\n"
        "      const root = startDir ? (path.isAbsolute(startDir) ? startDir : path.resolve(baseDir, startDir)) : baseDir;\n"
        "      const regexStr = pattern\n"
        '        .replace(/\\./g, "\\\\.")\n'
        '        .replace(/\\*\\*/g, ".*")\n'
        '        .replace(/(?<!\\.)\\*/g, "[^/]*")\n'
        '        .replace(/\\?/g, ".");\n'
        '      const regex = new RegExp(regexStr, "i");\n'
        "      const matches = await walkDir(root, regex, 100);\n"
        "      await pace();\n"
        "      return { matches, count: matches.length, root };\n"
        "    } catch (err: any) {\n"
        "      await pace();\n"
        "      return { error: `Glob error: ${err.message || String(err)}` };\n"
        "    }\n"
        "  },\n"
        "});\n"
    ),
    "grep.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n'
        'import * as fs from "node:fs/promises";\n'
        'import * as path from "node:path";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Search file contents by regex pattern on the host filesystem.",\n'
        "  inputSchema: z.object({\n"
        '    pattern: z.string().describe("Regex or text pattern to search for."),\n'
        '    path: z.string().optional().describe("Directory or file to search in (default: current workspace)."),\n'
        '    caseSensitive: z.boolean().optional().describe("Case sensitivity (default: false)."),\n'
        '    maxResults: z.number().optional().describe("Maximum number of line matches (default: 100)."),\n'
        "  }),\n"
        "  async execute({ pattern, path: searchPath, caseSensitive = false, maxResults = 100 }) {\n"
        "    try {\n"
        "      const baseDir = process.env.EVE_TARGET_WORKSPACE || process.cwd();\n"
        "      const root = searchPath ? (path.isAbsolute(searchPath) ? searchPath : path.resolve(baseDir, searchPath)) : baseDir;\n"
        '      const flags = caseSensitive ? "g" : "gi";\n'
        "      const regex = new RegExp(pattern, flags);\n"
        "      const matches: Array<{ file: string; line: number; text: string }> = [];\n\n"
        "      async function searchFile(filePath: string) {\n"
        "        if (matches.length >= maxResults) return;\n"
        "        try {\n"
        '          const content = await fs.readFile(filePath, "utf-8");\n'
        "          const lines = content.split(/\\r?\\n/);\n"
        "          for (let i = 0; i < lines.length; i++) {\n"
        "            if (regex.test(lines[i])) {\n"
        "              matches.push({ file: filePath, line: i + 1, text: lines[i].trim() });\n"
        "              if (matches.length >= maxResults) return;\n"
        "            }\n"
        "          }\n"
        "        } catch (_) {}\n"
        "      }\n\n"
        "      async function recurse(dir: string) {\n"
        "        if (matches.length >= maxResults) return;\n"
        "        try {\n"
        "          const entries = await fs.readdir(dir, { withFileTypes: true });\n"
        "          for (const entry of entries) {\n"
        "            if (matches.length >= maxResults) return;\n"
        '            if (entry.name === ".git" || entry.name === "node_modules" || entry.name === ".venv") continue;\n'
        "            const full = path.join(dir, entry.name);\n"
        "            if (entry.isDirectory()) {\n"
        "              await recurse(full);\n"
        "            } else {\n"
        "              await searchFile(full);\n"
        "            }\n"
        "          }\n"
        "        } catch (_) {}\n"
        "      }\n\n"
        "      const st = await fs.stat(root);\n"
        "      if (st.isDirectory()) {\n"
        "        await recurse(root);\n"
        "      } else {\n"
        "        await searchFile(root);\n"
        "      }\n\n"
        "      await pace();\n"
        "      return { matches, count: matches.length };\n"
        "    } catch (err: any) {\n"
        "      await pace();\n"
        "      return { error: `Grep error: ${err.message || String(err)}` };\n"
        "    }\n"
        "  },\n"
        "});\n"
    ),
    "web_fetch.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Fetch web content from a URL via HTTP GET.",\n'
        "  inputSchema: z.object({\n"
        '    url: z.string().describe("The URL to fetch."),\n'
        "  }),\n"
        "  async execute({ url }) {\n"
        "    try {\n"
        "      const res = await fetch(url);\n"
        "      const text = await res.text();\n"
        "      await pace();\n"
        "      return { status: res.status, content: text.slice(0, 50000) };\n"
        "    } catch (err: any) {\n"
        "      await pace();\n"
        "      return { error: `Failed to fetch URL: ${err.message || String(err)}` };\n"
        "    }\n"
        "  },\n"
        "});\n"
    ),
    "web_search.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Search the web for information.",\n'
        "  inputSchema: z.object({\n"
        '    query: z.string().describe("Search query string."),\n'
        "  }),\n"
        "  async execute({ query }) {\n"
        "    await pace();\n"
        "    return { query, results: [] };\n"
        "  },\n"
        "});\n"
    ),
    "todo.ts": (
        'import { defineTool } from "eve/tools";\n'
        'import { z } from "zod";\n\n'
        "async function pace() {\n"
        '  const ms = Number(process.env.EVE_TOOL_PACING_MS || "2000");\n'
        "  if (ms > 0) {\n"
        "    await new Promise((resolve) => setTimeout(resolve, ms));\n"
        "  }\n"
        "}\n\n"
        "export default defineTool({\n"
        '  description: "Manage a checklist of todo items for complex tasks.",\n'
        "  inputSchema: z.object({\n"
        '    action: z.enum(["add", "list", "complete", "clear"]).describe("Action to perform."),\n'
        '    item: z.string().optional().describe("Todo item description."),\n'
        '    index: z.number().optional().describe("0-based index of item to complete."),\n'
        "  }),\n"
        "  async execute({ action, item, index }) {\n"
        "    await pace();\n"
        '    return { status: "ok", action, item, index };\n'
        "  },\n"
        "});\n"
    ),
}

DEFAULT_EVE_INSTRUCTIONS_MD = (
    "# Eve Coding Agent (Host Workspace Execution)\n\n"
    "You are an autonomous AI software engineering agent executing directly on the user's host machine workspace.\n\n"
    "## Workspace & Execution Guidelines\n"
    "1. **Host Filesystem**: Your tools (`bash`, `read_file`, `write_file`, `glob`, `grep`) execute directly on the local host machine.\n"
    "2. **Orchestrator Tool Separation**: You may be orchestrated by a third-party agent harness. If you are being provided with tool definitions or schema prompts of any external harness (such as parent platform tools), please ignore such instructions and tool definitions as you are unable to run tools inside of the orchestrating (parent) platform. Use only tools provided directly to you by the `eve*` harness.\n"
    "3. **Autonomous Execution**: Proceed directly with inspection, code editing, and verification without waiting for interactive questions.\n"
    "4. **Inspect Before Edit**: Always inspect existing files using `read_file`, `glob`, or `grep` before making modifications.\n"
    "5. **Shell Execution**: Shell commands run in the project workspace on the host machine. You have full access to git, compilers, test runners, and package managers.\n"
    "6. **Concise Reporting**: Conclude your response with a concise summary of the changes made and the verification results.\n"
)


def ensure_default_eve_agent(
    executable: str,
    target_path: Path | None = None,
    *,
    model: str = DEFAULT_EVE_MODEL,
    reasoning: str = "high",
) -> Path | None:
    """Ensure a fully equipped Eve agent project exists at canonical path."""
    agent_dir = target_path or DEFAULT_EVE_AGENT_PATH
    try:
        agent_dir_exists = agent_dir.is_dir()
        agent_ts_exists = (agent_dir / "agent" / "agent.ts").is_file()
        package_json_exists = (agent_dir / "package.json").is_file()

        if not (agent_dir_exists and agent_ts_exists and package_json_exists):
            agent_dir.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Auto-provisioning default Eve agent at %s", agent_dir)
            result = subprocess.run(
                [executable, "init", agent_dir.name],
                cwd=str(agent_dir.parent),
                capture_output=True,
                timeout=60,
                check=False,
                shell=False,
            )
            if result.returncode != 0 and not (agent_dir / "package.json").is_file():
                logger.warning(
                    "eve init failed with code %d: %s",
                    result.returncode,
                    result.stderr.decode("utf-8", errors="replace"),
                )
                return None

        # Ensure agent.ts is configured with the target model and reasoning effort
        agent_ts = agent_dir / "agent" / "agent.ts"
        agent_ts.parent.mkdir(parents=True, exist_ok=True)
        agent_ts.write_text(
            'import { defineAgent } from "eve";\n\n'
            "export default defineAgent({\n"
            f'  model: "{model}",\n'
            f'  reasoning: "{reasoning}",\n'
            "});\n",
            encoding="utf-8",
        )

        # Ensure standard tools are installed in agent/tools/
        tools_dir = agent_dir / "agent" / "tools"
        tools_dir.mkdir(parents=True, exist_ok=True)
        for filename, code in STANDARD_EVE_TOOLS.items():
            tool_file = tools_dir / filename
            tool_file.write_text(code, encoding="utf-8")

        # Ensure instructions.md exists
        instructions_md = agent_dir / "agent" / "instructions.md"
        instructions_md.write_text(DEFAULT_EVE_INSTRUCTIONS_MD, encoding="utf-8")

        # Ensure Vercel project link / credentials exist for AI Gateway
        if (
            not (agent_dir / ".vercel" / "project.json").is_file()
            and not (agent_dir / ".env.local").is_file()
        ):
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["vercel", "link", "--yes"],
                    cwd=str(agent_dir),
                    capture_output=True,
                    timeout=30,
                    check=False,
                    shell=False,
                )

        return agent_dir.resolve()
    except Exception as e:
        logger.warning(
            "Failed to auto-provision default Eve agent at %s: %s", agent_dir, e
        )
        return None


def resolve_eve_agent_path(
    configured: str | None, project_dir: Path | None = None
) -> Path | None:
    """Resolve the directory containing an initialized Eve agent project."""
    candidates: list[Path] = []
    if configured and str(configured).strip():
        candidates.append(Path(str(configured).strip()))
    env_path = os.environ.get("EVE_AGENT_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    if project_dir is not None:
        candidates.append(project_dir)
    candidates.append(DEFAULT_EVE_AGENT_PATH)
    for c in candidates:
        try:
            if c.is_dir() and (
                (c / "agent" / "agent.ts").is_file() or (c / "package.json").is_file()
            ):
                return c.resolve()
        except OSError:
            continue
    return None


def resolve_eve_executable(configured: str | None) -> str | None:
    """Resolve the Eve CLI executable path."""
    for candidate in (
        (configured or "").strip(),
        os.environ.get("EVE_BINARY", "").strip(),
        os.environ.get("EVE_EXECUTABLE", "").strip(),
        "eve",
        "eve.cmd",
        "eve.exe",
    ):
        if not candidate:
            continue
        p = Path(candidate)
        if p.is_file():
            return str(p.resolve())
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def build_eve_acp_command(
    executable: str,
    *,
    extra_args: Sequence[str] | None = None,
    **_kwargs: Any,
) -> list[str]:
    """Construct the command line to spawn ``eve acp``."""
    cmd = [executable, "acp"]
    if extra_args:
        cmd.extend(list(extra_args))
    return cmd


class EveConfiguredModelEnumerator:
    """Enumerate model routes for configured Eve backend instances."""

    async def enumerate(
        self, instance_name: str, config: BackendConfig
    ) -> BackendModelEnumeration:
        extra = config.extra or {}
        configured_executable = extra.get("eve_executable")
        executable = resolve_eve_executable(
            str(configured_executable) if configured_executable else None
        )
        if executable is None:
            return BackendModelEnumeration.unavailable(
                instance_name=instance_name,
                connector="eve-acp",
                source="eve_configured",
                error_code="executable_not_found",
                instance_pinned=True,
            )

        configured_models = config.models or extra.get("models")
        if isinstance(configured_models, list) and configured_models:
            models = [
                add_vendor_prefix(strip_vendor_prefix(str(m).strip(), "eve"), "eve")
                for m in configured_models
                if str(m).strip()
            ]
            if models:
                return BackendModelEnumeration.available(
                    instance_name=instance_name,
                    connector="eve-acp",
                    models=models,
                    source="eve_configured",
                    instance_pinned=True,
                )

        default_model = str(extra.get("model") or DEFAULT_EVE_MODEL).strip()
        canonical_default = add_vendor_prefix(
            strip_vendor_prefix(default_model, "eve"), "eve"
        )
        models = [canonical_default]
        if canonical_default != "eve/auto":
            models.append("eve/auto")
        if canonical_default == "eve/zai/glm-5.2":
            models.append("eve/glm-5.2")
        return BackendModelEnumeration.available(
            instance_name=instance_name,
            connector="eve-acp",
            models=models,
            source="eve_configured",
            instance_pinned=True,
        )


class EveAcpConnector(BaseAcpConnector[ACPProcessRuntime]):
    """Vercel Eve agent runtime backend communicating via native ACP over stdio."""

    backend_type: str = "eve-acp"
    VENDOR_PREFIX: str = "eve"
    requires_explicit_workspace: bool = False

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        translation_service: TranslationService,
        **_: Any,
    ) -> None:
        super().__init__(config, translation_service=translation_service)
        self.client = client
        self.name = "eve-acp"
        self._eve_executable = "eve"
        self._agent_path: Path | None = None
        self._model = DEFAULT_EVE_MODEL
        self._configured_models: list[str] = []
        self._permission_policy = "allow"
        self._yolo = True
        self._mcp_servers: list[Any] = []
        self._extra_args: list[str] = []
        self._custom_env: dict[str, str] = {}
        self._process_timeout = DEFAULT_EVE_PROCESS_TIMEOUT_SECONDS
        self._idle_timeout = DEFAULT_EVE_IDLE_TIMEOUT_SECONDS
        self._reasoning = "high"
        self._tool_pacing_ms: int = 2000
        self._turn_pacing_delay_seconds: float = 2.0
        self._max_prompt_bytes: int = DEFAULT_EVE_MAX_PROMPT_BYTES

    async def initialize(self, **kwargs: Any) -> None:
        try:
            workspace, cfg_err = resolve_backend_init_acp_workspace(
                project_dir=kwargs.get("project_dir"),
                workspace_path=kwargs.get("workspace_path"),
                env_workspace=os.getenv("EVE_WORKSPACE"),
                env_source_label="EVE_WORKSPACE",
                is_usable=self._is_usable_directory,
            )
            if cfg_err:
                raise ConfigurationError(
                    message=cfg_err,
                    details={"error_code": "eve_acp_workspace_invalid"},
                )
            self._default_project_dir = workspace
            configured_executable = (
                kwargs.get("eve_executable")
                or kwargs.get("eve_binary")
                or kwargs.get("executable")
            )
            resolved_executable = resolve_eve_executable(
                str(configured_executable) if configured_executable else None
            )
            if resolved_executable is None:
                resolved_executable = str(configured_executable or self._eve_executable)
            self._eve_executable = resolved_executable

            configured_model = str(kwargs.get("model") or self._model)
            self._model = strip_vendor_prefix(configured_model, self.VENDOR_PREFIX)

            reasoning_effort = (
                str(
                    kwargs.get("reasoning_effort")
                    or kwargs.get("reasoning")
                    or self._reasoning
                )
                .strip()
                .lower()
            )
            if reasoning_effort in ("max", "x-high", "x_high"):
                reasoning_effort = "xhigh"
            self._reasoning = reasoning_effort

            agent_path = resolve_eve_agent_path(
                kwargs.get("agent_path")
                or kwargs.get("agent_dir")
                or kwargs.get("workspace_path"),
                workspace,
            )
            if agent_path is None:
                agent_path = await asyncio.to_thread(
                    ensure_default_eve_agent,
                    self._eve_executable,
                    DEFAULT_EVE_AGENT_PATH,
                    model=self._model,
                    reasoning=self._reasoning,
                )
            self._agent_path = agent_path

            configured_models = kwargs.get("models")
            if isinstance(configured_models, list):
                self._configured_models = [
                    strip_vendor_prefix(str(m).strip(), self.VENDOR_PREFIX)
                    for m in configured_models
                    if str(m).strip()
                ]

            self._permission_policy = str(
                kwargs.get("permission_policy") or self._permission_policy
            ).lower()
            if "yolo" in kwargs:
                self._yolo = bool(kwargs.get("yolo"))
            else:
                self._yolo = self._permission_policy == "allow"

            self._process_timeout = float(
                kwargs.get("process_timeout", self._process_timeout)
            )
            self._idle_timeout = float(kwargs.get("idle_timeout", self._idle_timeout))
            self._tool_pacing_ms = int(
                kwargs.get("tool_pacing_ms", self._tool_pacing_ms)
            )
            self._turn_pacing_delay_seconds = float(
                kwargs.get("turn_pacing_delay_seconds", self._turn_pacing_delay_seconds)
            )
            configured_max_prompt_bytes = kwargs.get(
                "max_prompt_bytes", self._max_prompt_bytes
            )
            try:
                self._max_prompt_bytes = int(configured_max_prompt_bytes)
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(
                    message="eve max_prompt_bytes must be a positive integer",
                    details={"max_prompt_bytes": configured_max_prompt_bytes},
                ) from exc
            if self._max_prompt_bytes <= 0:
                raise ConfigurationError(
                    message="eve max_prompt_bytes must be a positive integer",
                    details={"max_prompt_bytes": self._max_prompt_bytes},
                )
            if "rate_limit_backoff_delays" in kwargs:
                delays = kwargs.get("rate_limit_backoff_delays")
                if isinstance(delays, list | tuple) and delays:
                    self._rate_limit_backoff_delays = tuple(float(d) for d in delays)

            mcp = kwargs.get("mcp_servers", [])
            self._mcp_servers = list(mcp) if isinstance(mcp, list) else []

            extra = kwargs.get("eve_extra_args") or kwargs.get("extra_args")
            if isinstance(extra, list):
                self._extra_args = [str(arg) for arg in extra]
            elif isinstance(extra, str) and extra.strip():
                self._extra_args = [extra.strip()]

            custom_env = kwargs.get("env")
            if isinstance(custom_env, dict):
                self._custom_env = {
                    str(k): str(v) for k, v in custom_env.items() if k is not None
                }

            if not await self._check_eve_available():
                raise ConfigurationError(
                    message=f"eve executable not found: {self._eve_executable}",
                    details={
                        "executable": self._eve_executable,
                        "hint": "Ensure 'eve' is installed and in PATH or configure 'eve_executable'.",
                    },
                )

            self._validation_errors = []
            self._initialization_failed = False
            self.is_functional = True
        except Exception:
            self._initialization_failed = True
            self.is_functional = False
            self._validation_errors = ["eve-acp initialization failed"]
            raise

    async def _check_eve_available(self) -> bool:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [self._eve_executable, "--version"],
                capture_output=True,
                timeout=5,
                check=False,
                shell=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return False

    def _create_runtime(
        self, project_dir: Path, model: str, client_session_id: str = "default"
    ) -> ACPProcessRuntime:
        return ACPProcessRuntime(
            project_dir=project_dir,
            model=model,
            client_session_id=client_session_id,
            process_lock=asyncio.Lock(),
            request_lock=asyncio.Lock(),
            cancellation_lock=asyncio.Lock(),
            cancellation_event=asyncio.Event(),
        )

    def _subprocess_env(self, runtime: ACPProcessRuntime) -> dict[str, str]:
        env = os.environ.copy()
        env["LLM_PROXY_CALLER_BACKEND"] = "eve-acp"
        env["LLM_PROXY_ORIGIN_BACKEND"] = "eve-acp"
        env["EVE_TARGET_WORKSPACE"] = str(runtime.project_dir)
        env["EVE_TOOL_PACING_MS"] = str(self._tool_pacing_ms)
        current_hop = int(env.get("LLM_PROXY_HOP_COUNT", "0"))
        env["LLM_PROXY_HOP_COUNT"] = str(current_hop + 1)
        if self._custom_env:
            env.update(self._custom_env)
        return env

    async def _build_subprocess_command(self, runtime: ACPProcessRuntime) -> list[str]:
        return build_eve_acp_command(
            self._eve_executable,
            model=runtime.model,
            yolo=self._yolo,
            extra_args=self._extra_args,
        )

    def _resolve_project_dir_for_request(
        self, request: ConnectorChatCompletionsRequest
    ) -> Path:
        try:
            return super()._resolve_project_dir_for_request(request)
        except (ConfigurationError, BackendError):
            if self._default_project_dir is not None:
                return self._default_project_dir
            if self._agent_path is not None:
                return self._agent_path
            return Path.cwd()

    @staticmethod
    def _truncate_utf8(text: str, max_bytes: int) -> str:
        if max_bytes <= 0:
            return ""
        encoded = text.encode("utf-8")
        if len(encoded) <= max_bytes:
            return text
        omitted_marker = "\n...[middle of oversized prompt omitted]...\n"
        marker_bytes = len(omitted_marker.encode("utf-8"))
        if marker_bytes >= max_bytes:
            return encoded[:max_bytes].decode("utf-8", errors="ignore")
        content_bytes = max_bytes - marker_bytes
        head_bytes = content_bytes // 2
        tail_bytes = content_bytes - head_bytes
        head = encoded[:head_bytes].decode("utf-8", errors="ignore")
        tail = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
        return f"{head}{omitted_marker}{tail}"

    def _fit_prompt_to_transport_limit(
        self,
        runtime: ACPProcessRuntime,
        messages: Sequence[Any],
        user_message: str,
    ) -> str:
        """Bound Eve's ACP body while preserving the newest complete turns."""

        limit = self._max_prompt_bytes
        original_bytes = len(user_message.encode("utf-8"))
        if original_bytes <= limit:
            return user_message

        omission_note = (
            "[System Note: The ACP prompt exceeded Eve's transport budget. "
            "Older transcript entries were omitted; use the current request "
            "and available recent context as the source of truth.]\n\n"
        )
        available_bytes = max(1, limit - len(omission_note.encode("utf-8")))
        candidate = user_message

        state = runtime.history_state
        if state is not None and state.message_count < len(messages):
            start_candidates = range(state.message_count, len(messages))
        else:
            start_candidates = range(1, len(messages))

        for start_index in start_candidates:
            tail = ACPTranscriptSerializer.serialize_tail(messages, start_index)
            if tail and len(tail.encode("utf-8")) <= available_bytes:
                candidate = tail
                break

        if len(candidate.encode("utf-8")) > available_bytes:
            candidate = self._truncate_utf8(candidate, available_bytes)

        bounded = omission_note + candidate
        bounded_bytes = len(bounded.encode("utf-8"))
        logger.warning(
            "Bounded oversized Eve ACP prompt before dispatch: original_bytes=%d "
            "bounded_bytes=%d max_prompt_bytes=%d omitted_bytes=%d project=%s "
            "model=%s client_session=%s",
            original_bytes,
            bounded_bytes,
            limit,
            max(0, original_bytes - bounded_bytes),
            runtime.project_dir,
            runtime.model,
            runtime.client_session_id,
        )
        return bounded

    async def _create_isolated_agent_workspace(
        self, runtime: ACPProcessRuntime
    ) -> Path:
        """Create a disposable Eve app root for one ACP runtime.

        Eve's no-URL ACP mode owns and closes the dev server for its app root.
        A unique child app root gives each proxy runtime its own
        ``.eve/dev-server-state.v1.json`` and prevents one session's server or
        failed session state from being reused by another session. The shared
        parent ``node_modules`` remains discoverable through Node's normal
        ancestor lookup, so dependencies are not copied per session.
        """

        source_root = (self._agent_path or runtime.project_dir).resolve()

        def _copy_agent_root() -> Path:
            runtime_root = (
                source_root
                / ".eve"
                / f"{EVE_RUNTIME_DIRECTORY_PREFIX}{uuid.uuid4().hex}"
            )
            runtime_root.mkdir(parents=True, exist_ok=False)
            try:
                for entry in source_root.iterdir():
                    if entry.name in {".eve", ".git", "node_modules"}:
                        continue
                    destination = runtime_root / entry.name
                    if entry.is_dir():
                        shutil.copytree(entry, destination)
                    else:
                        shutil.copy2(entry, destination)
            except Exception:
                shutil.rmtree(runtime_root, ignore_errors=True)
                raise
            return runtime_root

        return await asyncio.to_thread(_copy_agent_root)

    def _cleanup_process_working_directory(
        self, runtime: ACPProcessRuntime, process_cwd: Path | None
    ) -> None:
        del runtime
        if process_cwd is None:
            return
        agent_root = self._agent_path
        if agent_root is None:
            return
        try:
            expected_parent = (agent_root / ".eve").resolve()
            candidate = process_cwd.resolve()
        except OSError:
            return
        if candidate.parent != expected_parent or not candidate.name.startswith(
            EVE_RUNTIME_DIRECTORY_PREFIX
        ):
            logger.warning(
                "Skipping cleanup of unexpected Eve subprocess directory: %s",
                candidate,
            )
            return
        shutil.rmtree(candidate, ignore_errors=True)

    async def _spawn_process(self, runtime: ACPProcessRuntime) -> None:
        assert runtime.process_lock is not None
        async with runtime.process_lock:
            process = runtime.process
            if process is not None and process.poll() is None:
                return

            if process is not None:
                # A dead child may have left a per-runtime app root behind.
                # Clear it before creating the next isolated root.
                self._cleanup_runtime_state(runtime, process)

            cmd = await self._build_subprocess_command(runtime)
            spawn_cwd = await self._create_isolated_agent_workspace(runtime)
            runtime.process_cwd = spawn_cwd

            new_process: subprocess.Popen[bytes] | None = None
            try:
                new_process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(spawn_cwd),
                    shell=False,
                    env=self._subprocess_env(runtime),
                    creationflags=(
                        subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
                    ),
                )
                runtime.process = new_process
                runtime.stderr_drain_stop_event.clear()
                with runtime.stderr_tail_lock:
                    runtime.stderr_tail.clear()
                runtime.stderr_drain_thread = threading.Thread(
                    target=self._drain_stderr_thread,
                    args=(new_process, runtime),
                    name=f"acp-stderr-{new_process.pid}",
                    daemon=True,
                )
                runtime.stderr_drain_thread.start()
                await asyncio.sleep(0.1)
                if new_process.poll() is not None:
                    stderr = await self._read_stderr(new_process, runtime)
                    raise BackendError(
                        message=f"eve process exited immediately with code {new_process.returncode}",
                        details={"exit_code": new_process.returncode, "stderr": stderr},
                    )
                runtime.last_activity = asyncio.get_running_loop().time()
                runtime.initialized = False
                self._reset_protocol_runtime_state(runtime)
                runtime.message_id = 0
                runtime.history_state = None
                runtime.last_prompt_params = None
                runtime.acp_subprocess_identity = capture_acp_subprocess_identity(
                    new_process, cmd
                )
            except BaseException as e:
                if new_process is not None and new_process.poll() is None:
                    with contextlib.suppress(Exception):
                        await self._terminate_process(new_process)
                self._cleanup_runtime_state(runtime, new_process)
                if isinstance(e, BackendError):
                    raise
                raise BackendError(
                    message=f"Failed to spawn eve process: {e}",
                    details={"command": cmd, "error": str(e)},
                ) from e

    async def _perform_handshake(self, runtime: ACPProcessRuntime) -> None:
        initialize_id = await self._send_jsonrpc_message(
            runtime,
            "initialize",
            {
                "protocolVersion": ACP_PROTOCOL_VERSION,
                "clientCapabilities": {
                    "fs": {"readFile": False, "writeFile": False},
                    "terminal": False,
                },
                "clientInfo": {
                    "name": "llm-interactive-proxy",
                    "version": "1.0",
                },
            },
        )
        initialize_response = await self._await_response(runtime, initialize_id)
        if initialize_response.is_error and initialize_response.error is not None:
            raise BackendError(
                message=f"eve initialize failed: {initialize_response.error.message}",
                details=initialize_response.error.model_dump(),
            )

        session_new_id = await self._send_jsonrpc_message(
            runtime,
            "session/new",
            {
                "cwd": str(
                    runtime.process_cwd or self._agent_path or runtime.project_dir
                ),
                "mcpServers": self._mcp_servers,
            },
        )
        session_new_response = await self._await_response(runtime, session_new_id)
        if session_new_response.is_error and session_new_response.error is not None:
            raise BackendError(
                message=f"eve session/new failed: {session_new_response.error.message}",
                details=session_new_response.error.model_dump(),
            )

        session_result = session_new_response.result or {}
        session_id = session_result.get("sessionId")
        if not isinstance(session_id, str) or not session_id.strip():
            raise BackendError(
                message="eve session/new did not return a valid sessionId",
                details={"result": session_result},
            )

        runtime.session_id = session_id
        runtime.initialized = True

    async def _handle_server_request(
        self, runtime: ACPProcessRuntime, msg: ACPNotification
    ) -> None:
        assert msg.id is not None
        rid = msg.id
        method = msg.method or ""

        if method == "session/request_permission":
            if self._permission_policy == "deny":
                await self._send_jsonrpc_result(
                    runtime,
                    rid,
                    {"outcome": {"outcome": "selected", "optionId": "reject-once"}},
                )
            else:
                # Default "allow" / "yolo"
                await self._send_jsonrpc_result(
                    runtime,
                    rid,
                    {"outcome": {"outcome": "selected", "optionId": "allow-always"}},
                )
            return

        if method.startswith(("eve/", "custom/")):
            if logger.isEnabledFor(logging.INFO):
                logger.info("Handling Eve ACP extension %s with empty result", method)
            await self._send_jsonrpc_result(runtime, rid, {})
            return

        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unhandled Eve inbound JSON-RPC method=%s id=%s; returning -32601",
                method,
                rid,
            )
        await self._write_json_line(
            runtime,
            {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"Method not handled: {method}"},
            },
        )

    def get_available_models(self) -> list[str]:
        if self._configured_models:
            return [
                add_vendor_prefix(m, self.VENDOR_PREFIX)
                for m in self._configured_models
            ]
        return [add_vendor_prefix(self._model, self.VENDOR_PREFIX)]


from src.core.services.backend_registry import backend_registry

backend_registry.register_backend("eve-acp", EveAcpConnector)
