import datetime

PY = "c:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy\\.venv\\Scripts\\python.exe"
FILES_TO_PROCESS = [
    "tests/unit/core/services/test_response_processor_service.py",
    "tests/unit/test_response_parser_service.py",
    "src/core/di/services.py",
    "src/core/app/stages/processor.py",
    "src/core/app/stages/core_services.py",
]

start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
project_root = "c:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy"
venv_relative = ".venv"

status_content = f"# Python QA Agent Status\n\n## Run Info\n- Start: {start_time}\n- Project root: {project_root}\n- Venv (relative): {venv_relative}\n- Files:\n"
for f in FILES_TO_PROCESS:
    status_content += f"  - {f}\n"

status_content += "\n## Iterations\n\n## Final Validation\n\n## Changes by File\n\n## Blocked (if any)\n\n## Outcome\n"

with open(
    "c:\\Users\\Mateusz\\source\\repos\\llm-interactive-proxy\\.python_qa_mcp_server\\status.md",
    "w",
) as f:
    f.write(status_content)
