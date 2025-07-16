# Kiro Steering System Documentation

The Kiro steering system provides a powerful way to include additional context, instructions, and project-specific guidelines in your interactions with the AI assistant. This system helps maintain consistency across development sessions and ensures that project standards are automatically applied.

## Overview

Steering files are Markdown documents that contain project-specific guidance, coding standards, and behavioral preferences that influence how Kiro operates within your workspace. They provide a way to encode team knowledge and project conventions directly into the AI assistant's context.

## What is Steering?

Steering files contain:
- Project-specific coding standards and conventions
- Team norms and best practices
- Build, test, and deployment instructions
- Response guidelines and behavioral preferences
- References to important project documentation
- Environment setup requirements
- Quality assurance guidelines

## Location and Structure

Steering files are stored in `.kiro/steering/*.md` within your workspace. Each file follows this structure:

```markdown
---
inclusion: always|fileMatch|manual
fileMatchPattern: 'pattern*' # (optional, for fileMatch inclusion)
---

# Steering Content

Your markdown content with instructions and guidelines.

## File References
You can reference other files using: #[[file:relative/path/to/file.ext]]
```

## Inclusion Modes

Steering files support three inclusion modes that determine when they are applied:

### 1. Always Included (Default)
```yaml
---
inclusion: always
---
```
These files are automatically included in every interaction with Kiro. Use this for:
- Core project standards
- Universal coding conventions
- Essential response guidelines
- Environment setup requirements

### 2. Conditional Inclusion
```yaml
---
inclusion: fileMatch
fileMatchPattern: 'README*'
---
```
These files are included only when specific files matching the pattern are read into context. Use this for:
- Documentation-specific guidelines
- File-type specific standards
- Context-sensitive instructions

### 3. Manual Inclusion
```yaml
---
inclusion: manual
---
```
These files are included only when explicitly referenced using context keys (`#steering-name` in chat). Use this for:
- Specialized workflows
- Optional guidelines
- Situational instructions

## File References

Steering files can automatically include content from other project files using the special syntax:

```markdown
#[[file:openapi.yaml]]
#[[file:docs/architecture.md]]
#[[file:package.json]]
```

This allows you to:
- Reference API specifications during implementation
- Include architectural decisions in context
- Pull in configuration files for reference
- Maintain single sources of truth

## Example Steering Files

### Response Guidelines (`do-not-signal-success.md`)
```yaml
---
inclusion: always
---

# Response Guidelines

When completing tasks successfully, avoid explicitly stating completion or success. Instead:

- Proceed directly to the next logical step if there is one
- Provide the requested output or information without announcing completion
- Let the results speak for themselves
- Only mention completion status if the user specifically asks about it or if there are errors/issues to report

This keeps interactions focused and efficient, reducing unnecessary verbal overhead.
```

### Environment Setup (`activate-venv.md`)
```yaml
---
inclusion: always
---

# Python Environment Requirements

Before executing any Python command ensure you activate venv from the `.venv` directory.
You are not allowed to execute any Python commands including python, pip, pytest without activating the '.venv` first (note the dot at the beginning).

## Activation Commands
- Windows: `.venv\Scripts\activate`
- Unix/macOS: `source .venv/bin/activate`
```

### Code Quality Standards (`code-standards.md`)
```yaml
---
inclusion: fileMatch
fileMatchPattern: '*.py'
---

# Python Code Standards

## Style Guidelines
- Follow PEP 8 conventions
- Use type hints for all function parameters and return values
- Maximum line length: 88 characters (Black formatter)
- Use docstrings for all public functions and classes

## Testing Requirements
- Minimum 80% code coverage
- Unit tests for all business logic
- Integration tests for API endpoints
- Use pytest fixtures for test setup

## File References
#[[file:pyproject.toml]]
#[[file:pytest.ini]]
```

### API Development (`api-guidelines.md`)
```yaml
---
inclusion: manual
---

# API Development Guidelines

## OpenAPI Specification
#[[file:openapi.yaml]]

## Standards
- RESTful endpoint design
- Consistent error response format
- Proper HTTP status codes
- Comprehensive input validation
- Rate limiting implementation

## Authentication
- JWT tokens for user authentication
- API keys for service-to-service communication
- Proper token expiration handling
```

## Managing Steering Files

### Creating Steering Files
You can create steering files by:
1. Directly creating `.md` files in `.kiro/steering/`
2. Asking Kiro to create steering files for you
3. Using the Kiro interface to manage configurations

### Updating Steering Files
- Edit files directly in your preferred editor
- Ask Kiro to modify existing steering files
- Version control steering files with your project

### Organizing Steering Files
Use descriptive filenames that indicate their purpose:
- `response-guidelines.md`
- `python-standards.md`
- `testing-requirements.md`
- `deployment-process.md`
- `security-guidelines.md`

## Best Practices

### Content Guidelines
- **Be Specific**: Provide concrete examples and clear instructions
- **Stay Current**: Regularly update steering files as project requirements evolve
- **Be Concise**: Focus on essential information to avoid overwhelming context
- **Use Examples**: Include code snippets and practical examples

### Organization Tips
- **Single Responsibility**: Each steering file should focus on one area
- **Logical Grouping**: Group related guidelines in the same file
- **Clear Naming**: Use descriptive filenames that indicate content
- **Consistent Format**: Maintain consistent structure across files

### Inclusion Strategy
- **Always**: Core standards that apply to all work
- **Conditional**: Context-specific guidelines
- **Manual**: Specialized or optional instructions

### File References
- **Keep Current**: Ensure referenced files exist and are up-to-date
- **Use Relative Paths**: Reference files relative to workspace root
- **Document Dependencies**: Note when steering depends on external files

## Benefits

### For Individual Developers
- **Consistency**: Maintain consistent coding style and practices
- **Efficiency**: Reduce time spent explaining project conventions
- **Quality**: Automatic application of best practices
- **Learning**: Encode team knowledge for easy access

### For Teams
- **Standardization**: Ensure all team members follow same guidelines
- **Onboarding**: New team members get instant access to project standards
- **Knowledge Sharing**: Capture and share institutional knowledge
- **Compliance**: Maintain adherence to organizational standards

### for Projects
- **Maintainability**: Consistent code structure and documentation
- **Quality Assurance**: Automatic application of quality standards
- **Documentation**: Living documentation that stays current
- **Automation**: Reduce manual oversight and review overhead

## Troubleshooting

### Common Issues

**Steering File Not Applied**
- Check file location (must be in `.kiro/steering/`)
- Verify front-matter syntax (YAML format)
- Ensure inclusion mode is appropriate for use case

**File References Not Working**
- Verify file paths are relative to workspace root
- Check that referenced files exist
- Ensure proper syntax: `#[[file:path/to/file]]`

**Too Much Context**
- Review inclusion modes (consider conditional vs always)
- Split large steering files into focused components
- Use manual inclusion for specialized guidelines

**Conflicting Guidelines**
- Review all active steering files for conflicts
- Use specific inclusion patterns to avoid conflicts
- Prioritize guidelines by importance and specificity

### Debugging Tips
- List active steering files using Kiro commands
- Review which files are included in current context
- Test steering files with simple examples
- Use version control to track steering file changes

## Advanced Usage

### Dynamic Content
Steering files can include dynamic references that change based on context:
```markdown
Current project configuration: #[[file:package.json]]
API specification: #[[file:api/openapi.yaml]]
```

### Conditional Logic
Use file matching patterns for sophisticated inclusion:
```yaml
---
inclusion: fileMatch
fileMatchPattern: 'src/**/*.ts'
---
# TypeScript-specific guidelines only when working with TS files
```

### Integration with CI/CD
- Include steering files in code reviews
- Validate steering file syntax in CI pipelines
- Use steering files to enforce coding standards
- Generate documentation from steering files

This steering system transforms Kiro from a general-purpose AI assistant into a project-aware, standards-compliant development partner that understands your specific context and requirements.