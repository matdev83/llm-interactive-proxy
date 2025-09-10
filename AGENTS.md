# Agent Development Guidelines

## Never Use Unicode Emojis
- Use ASCII characters instead of emojis
- Avoid using emojis in code comments or docstrings

## Build/Lint/Test Commands
- Install dependencies: `./.venv/Scripts/python.exe -m pip install -e .[dev]`
- Run all tests: `./.venv/Scripts/python.exe -m pytest`
- Run specific test: `./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_name`
- Lint code: `./.venv/Scripts/python.exe -m ruff --fix check .`
- Format code: `./.venv/Scripts/python.exe -m black .`

## Code Style Guidelines
- Follow PEP 8 and use type hints for all functions
- Use ruff for linting (see ruff.toml) and black for formatting
- Import order: standard library, third-party, local imports (separated by blank lines)
- Naming conventions: snake_case for variables/functions, PascalCase for classes
- Error handling: Use specific exceptions and include meaningful error messages
- Prefer f-strings for string formatting

### Error Handling Strategy

The project uses a custom exception hierarchy to provide detailed and consistent error information. All custom exceptions inherit from `LLMProxyError`.

When handling errors, follow these guidelines:

- **Catch specific exceptions** whenever possible. Avoid broad `except Exception` blocks.
- If a broad exception must be caught, **log the error with `exc_info=True`** and re-raise a more specific custom exception.
- Use the most specific exception class available from `src.core.common.exceptions` that accurately describes the error.
- When creating new exceptions, ensure they inherit from the appropriate base class (e.g., `BackendError`, `CommandError`).
- Provide clear, helpful error messages and include relevant details in the `details` dictionary of the exception.

## Development Workflow
1. Write tests first (TDD)
2. Run tests to confirm they fail: `./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_name`
3. Implement minimal code to pass tests
4. Run linter: `./.venv/Scripts/python.exe -m ruff --fix check .`
5. Run all tests: `./.venv/Scripts/python.exe -m pytest`

## Code Quality Standards
- Follow SOLID principles:
  - Single Responsibility Principle (SRP): A class should have only one reason to change
  - Open/Closed Principle (OCP): Software entities should be open for extension, but closed for modification
  - Liskov Substitution Principle (LSP): Objects should be replaceable with instances of their subtypes
  - Interface Segregation Principle (ISP): Clients should not be forced to depend on interfaces they do not use
  - Dependency Inversion Principle (DIP): High-level modules should not depend on low-level modules
- Apply DRY (Don't Repeat Yourself) principle to avoid code duplication
- Maintain modular and layered architecture with clear separation of concerns
- Ensure easy testability of all components
- Write code that is maintainable and follows established patterns

## Project Improvement Guidelines
- Agents should only make changes that improve the codebase:
  - Add new functions/methods
  - Improve existing functions/methods
  - Improve code structure and maintainability
  - Add new functionalities
- Agents are NOT allowed to degrade the project by:
  - Removing functions or functionalities
  - Removing files or features
  - Degrading code quality
- Exceptions: Only remove code/features when EXPLICITLY requested by the user

## Dependency Management
- Agents are NOT allowed to manually install any modules by issuing `pip` commands
- All dependency management MUST be done by modifications to the pyproject.toml file
- After adding new dependency, install dependencies with: `./.venv/Scripts/python.exe -m pip install -e .[dev]`

## Project Structure
- src/: Source code
- tests/: Unit and integration tests
- config/: Configuration files
- docs/: Documentation
- examples/: Usage examples

## Important Notes
- Development is being made on Windows PC
- Linux based coding agents are using WSL and are expected to still use this Python binary: `./.venv/Scripts/python.exe` even if they believe they should use the linux-one
- Make sure it is clear that all executions of Python based commands use this exact interpreter (exe file) from within the .venv folder
- Always activate virtual environment from .venv before running commands
- Prove code works by running tests before submitting tasks