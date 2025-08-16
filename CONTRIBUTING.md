# Contributing to LLM Interactive Proxy

Thank you for your interest in contributing to the LLM Interactive Proxy! This document provides guidelines and instructions for contributing to the project.

## Code of Conduct

Please be respectful and considerate when interacting with other contributors. We aim to create a welcoming and inclusive environment for everyone.

## Getting Started

1. **Fork the repository** on GitHub.
1. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/llm-interactive-proxy.git
   cd llm-interactive-proxy
   ```
1. **Create a virtual environment** and install dependencies:
   ```bash
   python -m venv .venv
   # On Linux/macOS
   source .venv/bin/activate
   # On Windows
   .venv\Scripts\activate

   pip install -e .[dev]
   ```
1. **Create a feature branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

1. **Check the existing issues** for tasks to work on or create a new issue to discuss your proposed changes.
1. **Make your changes** following the project's architecture and coding standards.
1. **Write or update tests** for your changes.
1. **Run the linters and formatters** to ensure code quality:
   ```bash
   # Run ruff linter
   ruff check --fix src/
   # Run Black formatter
   black src/
   # Run MyPy type checker
   mypy src/
   ```
1. **Run the tests** to ensure everything works:
   ```bash
   pytest
   ```
1. **Commit your changes** with descriptive commit messages.
1. **Push your changes** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
1. **Submit a pull request** to the main repository.

## Architecture and Design Principles

The LLM Interactive Proxy follows a clean architecture approach based on SOLID principles. Please refer to the [Developer Guide](docs/DEVELOPER_GUIDE.md) for detailed information on the architecture.

When contributing code, please follow these principles:

1. **Single Responsibility Principle (SRP)**: Each class should have only one reason to change.
1. **Open/Closed Principle (OCP)**: Classes should be open for extension but closed for modification.
1. **Liskov Substitution Principle (LSP)**: Subtypes must be substitutable for their base types.
1. **Interface Segregation Principle (ISP)**: Clients shouldn't depend on interfaces they don't use.
1. **Dependency Inversion Principle (DIP)**: Depend on abstractions, not concrete implementations.

## Coding Standards

- **Type Hints**: Use Python type hints for function parameters and return values.
- **Docstrings**: Add docstrings to all public methods and classes using Google style format.
- **Tests**: Write tests for new functionality or bug fixes.
- **PEP 8**: Follow PEP 8 style guidelines as enforced by Black and Ruff.

## Pull Request Guidelines

- **Focused Changes**: Each pull request should address a single issue or feature.
- **Documentation**: Update the documentation to reflect your changes if necessary.
- **Tests**: Include tests for your changes.
- **Linting**: Ensure your code passes linting checks.
- **Descriptive PR**: Provide a clear description of the changes and why they are needed.

## Feature Requests and Bug Reports

- **Feature Requests**: Open an issue with a clear description of the feature and why it would be valuable.
- **Bug Reports**: Include steps to reproduce, expected behavior, actual behavior, and environment details.

## Adding New Backends

To add a new LLM backend connector:

1. Create a new file in `src/connectors/` implementing the `LLMBackend` abstract class.
1. Add appropriate configuration options in `src/core/config/app_config.py`.
1. Update the `BackendFactory` in `src/core/services/backend_factory.py` to support the new backend.
1. Add tests for the new backend connector.
1. Update the documentation to include the new backend.

## Adding New Commands

To add a new in-chat command:

1. Create a new command handler in `src/commands/` following the command pattern.
1. Register the command in the command registry.
1. Add tests for the new command.
1. Update the documentation to include the new command.

## Working with Configuration

The project uses a modern, type-safe configuration system. When working with configuration:

### Configuration Interfaces

Always depend on configuration interfaces, not concrete implementations:

```python
from src.core.interfaces.configuration import IBackendConfig, IReasoningConfig

class MyService:
    def __init__(self, backend_config: IBackendConfig, reasoning_config: IReasoningConfig):
        self._backend_config = backend_config
        self._reasoning_config = reasoning_config
```

### Adding New Configuration Options

1. **Define the interface** in `src/core/interfaces/configuration.py`
2. **Implement the domain model** in `src/core/domain/configuration.py`
3. **Register with DI container** in the application factory
4. **Add environment variable handling** in the config loader
5. **Write tests** for the new configuration options
6. **Update documentation** including the new [Configuration Guide](docs/CONFIGURATION.md)

### Configuration Best Practices

- Use immutable configuration objects (frozen Pydantic models)
- Implement proper interfaces for all configuration types
- Use the builder pattern (`with_*` methods) for modifications
- Validate configuration at application startup
- Write comprehensive tests for configuration objects

## Documentation Changes

Documentation improvements are always welcome. Please follow these guidelines:

1. Ensure documentation is clear and concise.
1. Update relevant sections when adding new features or changing existing ones.
1. Use consistent formatting and style.

## License

By contributing to the LLM Interactive Proxy, you agree that your contributions will be licensed under the project's license.

## Questions and Support

If you have questions about contributing or need help, please open an issue labeled "question" or "help wanted".

Thank you for contributing to the LLM Interactive Proxy!
