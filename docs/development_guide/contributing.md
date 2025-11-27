# Contributing

We welcome contributions to the LLM Interactive Proxy! This guide covers the contribution workflow, pull request guidelines, and code review process.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git
- GitHub account
- Familiarity with the project (read [README.md](../../README.md))

### Setting Up Development Environment

1. **Fork the repository** on GitHub

2. **Clone your fork**:

   ```bash
   git clone https://github.com/YOUR_USERNAME/llm-interactive-proxy.git
   cd llm-interactive-proxy
   ```

3. **Add upstream remote**:

   ```bash
   git remote add upstream https://github.com/matdev83/llm-interactive-proxy.git
   ```

4. **Create virtual environment**:

   ```bash
   python -m venv .venv
   ```

5. **Activate virtual environment**:
   - Windows: `.\.venv\Scripts\activate`
   - Linux/macOS: `source .venv/bin/activate`

6. **Install dependencies**:

   ```bash
   ./.venv/Scripts/python.exe -m pip install -e .[dev]
   ```

7. **Install pre-commit hooks**:

   ```bash
   ./.venv/Scripts/python.exe scripts/install-hooks.py
   ```

## Contribution Workflow

### 1. Create a Feature Branch

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name
```

**Branch Naming Conventions**:

- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test additions or improvements

### 2. Make Your Changes

Follow Test-Driven Development (TDD):

1. **Write tests first**:

   ```bash
   # Create test file
   # tests/unit/test_your_feature.py
   ```

2. **Run tests (should fail)**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/test_your_feature.py
   ```

3. **Implement feature**:

   ```python
   # src/module.py
   ```

4. **Run tests (should pass)**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/unit/test_your_feature.py
   ```

5. **Run all tests**:

   ```bash
   ./.venv/Scripts/python.exe -m pytest
   ```

### 3. Ensure Code Quality

```bash
# Format code
./.venv/Scripts/python.exe -m black .

# Lint code
./.venv/Scripts/python.exe -m ruff check --fix .

# Type check
./.venv/Scripts/python.exe -m mypy src/

# Run all tests with coverage
./.venv/Scripts/python.exe -m pytest --cov=src
```

### 4. Commit Your Changes

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
type(scope): subject

body (optional)

footer (optional)
```

**Types**:

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions or improvements
- `chore`: Build process or auxiliary tool changes

**Examples**:

```bash
git commit -m "feat(connectors): add support for new LLM provider"
git commit -m "fix(loop-detection): correct pattern matching logic"
git commit -m "docs(readme): update installation instructions"
```

### 5. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

### 6. Create Pull Request

1. Go to your fork on GitHub
2. Click "New Pull Request"
3. Select your feature branch
4. Fill out the PR template:
   - **Title**: Use Conventional Commits format
   - **Description**: Explain what and why
   - **Related Issues**: Link to related issues
   - **Testing**: Describe how you tested
   - **Screenshots**: If applicable

## Pull Request Guidelines

### PR Title

Use Conventional Commits format:

```
feat(scope): add new feature
fix(scope): fix bug in component
docs(scope): update documentation
```

### PR Description

Include:

1. **What**: What does this PR do?
2. **Why**: Why is this change needed?
3. **How**: How does it work?
4. **Testing**: How was it tested?
5. **Related Issues**: Fixes #123, Closes #456

**Template**:

```markdown
## Description

Brief description of the changes.

## Motivation

Why is this change needed? What problem does it solve?

## Changes

- Change 1
- Change 2
- Change 3

## Testing

How was this tested?

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Related Issues

Fixes #123
```

### PR Checklist

Before submitting, ensure:

- [ ] Tests pass locally
- [ ] Code is formatted (black)
- [ ] Code is linted (ruff)
- [ ] Type checking passes (mypy)
- [ ] Documentation is updated
- [ ] Commit messages follow Conventional Commits
- [ ] PR description is complete
- [ ] Pre-commit hooks pass

## Code Review Process

### Review Timeline

- Initial review: Within 2-3 business days
- Follow-up reviews: Within 1-2 business days
- Merge: After approval and CI passes

### Review Criteria

Reviewers will check:

1. **Functionality**: Does it work as intended?
2. **Tests**: Are there adequate tests?
3. **Code Quality**: Does it follow coding standards?
4. **Architecture**: Does it fit the architecture?
5. **Documentation**: Is it documented?
6. **Performance**: Are there performance concerns?
7. **Security**: Are there security implications?

### Addressing Review Comments

1. **Read carefully**: Understand the feedback
2. **Ask questions**: If unclear, ask for clarification
3. **Make changes**: Address the feedback
4. **Respond**: Reply to comments explaining changes
5. **Request re-review**: When ready

**Example Response**:

```markdown
> Consider using a more descriptive variable name here.

Good point! Changed `x` to `backend_connector` for clarity.
```

### Resolving Conflicts

If your branch has conflicts with main:

```bash
# Update main
git checkout main
git pull upstream main

# Rebase your branch
git checkout feature/your-feature-name
git rebase main

# Resolve conflicts
# Edit conflicting files
git add .
git rebase --continue

# Force push (rebase rewrites history)
git push --force-with-lease origin feature/your-feature-name
```

## Coding Standards

Follow the project's coding standards (see [AGENTS.md](../../AGENTS.md)):

### Code Style

- **PEP 8**: Follow Python style guide
- **Type Hints**: Use type hints for all functions
- **Docstrings**: Document all public functions/classes
- **Naming**: Use descriptive names

### Architecture Principles

- **SOLID Principles**: Follow SOLID design principles
- **DRY**: Don't Repeat Yourself
- **Interface-Driven**: Define interfaces before implementations
- **Dependency Injection**: Use DI for dependencies
- **Immutable Models**: Use immutable Pydantic models

### Testing Standards

- **TDD**: Write tests first
- **Coverage**: Aim for 80%+ coverage
- **Unit Tests**: Test components in isolation
- **Integration Tests**: Test component interactions
- **Property Tests**: Use Hypothesis for property-based testing

## Security Guidelines

### API Key Handling

- **Never log secrets**: Don't print API keys or tokens
- **Use redaction**: Rely on global logging redaction
- **Environment variables**: Store keys in environment variables
- **No hardcoding**: Never hardcode keys in code

### Pre-Commit Hooks

The project uses mandatory pre-commit hooks that:

- **Scan for secrets**: Detect API keys and tokens
- **Block commits**: Prevent commits with secrets
- **Check architecture**: Validate architectural constraints

**Running manually**:

```bash
./.venv/Scripts/python.exe scripts/pre_commit_api_key_check.py
```

### Security Best Practices

- Use environment variables for sensitive data
- Keep `.env` files untracked
- Never commit credentials
- Rotate keys if leaked
- Audit CI logs for leaks

## Documentation Guidelines

### When to Update Documentation

Update documentation when:

- Adding new features
- Changing existing behavior
- Fixing bugs that affect usage
- Adding configuration options
- Changing APIs

### Documentation Types

1. **README.md**: High-level overview and quick start
2. **User Guide** (`docs/user_guide/`): Feature documentation
3. **Development Guide** (`docs/development_guide/`): Developer documentation
4. **Code Comments**: Inline documentation
5. **Docstrings**: Function/class documentation

### Documentation Standards

- **Clear and concise**: Use simple language
- **Examples**: Provide code examples
- **Complete**: Cover all aspects
- **Up-to-date**: Keep in sync with code
- **Formatted**: Use proper Markdown formatting

## Common Contribution Scenarios

### Adding a New Feature

1. Create feature branch
2. Write tests for the feature
3. Implement the feature
4. Update documentation
5. Submit PR

### Fixing a Bug

1. Create fix branch
2. Write test that reproduces bug
3. Fix the bug
4. Verify test passes
5. Submit PR with "Fixes #issue" in description

### Improving Documentation

1. Create docs branch
2. Make documentation changes
3. Preview changes locally
4. Submit PR

### Adding a New Backend

See [adding-backends.md](adding-backends.md) for detailed guide.

## Troubleshooting

### Tests Failing

```bash
# Run specific test
./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py::test_name -v

# Run with debug output
./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py -s

# Run with pdb debugger
./.venv/Scripts/python.exe -m pytest tests/unit/test_file.py --pdb
```

### Pre-Commit Hook Failing

```bash
# Run hook manually
./.venv/Scripts/python.exe scripts/pre-commit-hook.py

# Check for secrets
./.venv/Scripts/python.exe scripts/pre_commit_api_key_check.py

# Reinstall hooks
./.venv/Scripts/python.exe scripts/install-hooks.py
```

### Import Errors

```bash
# Reinstall package
./.venv/Scripts/python.exe -m pip install -e .[dev]

# Verify installation
./.venv/Scripts/python.exe -c "import src; print(src.__file__)"
```

## Getting Help

### Resources

- **Documentation**: Read the docs in `docs/`
- **Issues**: Search existing issues on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Code**: Read the source code and tests

### Asking Questions

When asking for help:

1. **Search first**: Check if question already answered
2. **Be specific**: Provide details and context
3. **Include code**: Share relevant code snippets
4. **Show effort**: Explain what you've tried
5. **Be patient**: Wait for responses

### Reporting Bugs

When reporting bugs:

1. **Search first**: Check if bug already reported
2. **Minimal reproduction**: Provide minimal example
3. **Environment**: Include Python version, OS, etc.
4. **Expected vs actual**: Describe expected and actual behavior
5. **Logs**: Include relevant logs or error messages

## Community Guidelines

- **Be respectful**: Treat everyone with respect
- **Be constructive**: Provide helpful feedback
- **Be patient**: Everyone is learning
- **Be collaborative**: Work together
- **Follow Code of Conduct**: Adhere to project's code of conduct

## Related Documentation

- **Architecture**: See [architecture.md](architecture.md) for system architecture
- **Code Organization**: See [code-organization.md](code-organization.md) for project structure
- **Building**: See [building.md](building.md) for build instructions
- **Testing**: See [testing.md](testing.md) for testing guidelines
- **Adding Features**: See [adding-features.md](adding-features.md) for feature development
- **Adding Backends**: See [adding-backends.md](adding-backends.md) for backend development
- **Coding Standards**: See [AGENTS.md](../../AGENTS.md) for detailed coding standards
