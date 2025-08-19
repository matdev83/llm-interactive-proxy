# QA Workflow (archived snapshot)

Project-wide QA Quality Gate (Ruff → Black → Ruff → Mypy)

Execution plan summary:
- Run Ruff autofix on src and tests
- Run Black
- Repeat Ruff until idempotent
- Run Mypy

Guardrails: do not modify `app_config.py`, `application_factory.py`, or `conftest.py` during QA pass unless necessary.


