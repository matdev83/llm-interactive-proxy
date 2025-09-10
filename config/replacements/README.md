# Content Rewriting Configuration

This directory contains configuration files for the content rewriting feature.

## Directory Structure

```
config/replacements/
├── prompts/
│   ├── system/      # System prompt rewriting rules
│   └── user/        # User prompt rewriting rules
└── replies/         # Response rewriting rules
```

## Rule Configuration

Each rule is defined in a numbered directory (e.g., `001_example`, `002_another_rule`) and contains:

- `SEARCH.txt` - The text pattern to search for (minimum 8 characters)
- One of the following action files:
  - `REPLACE.txt` - Replacement text
  - `PREPEND.txt` - Text to prepend before the match
  - `APPEND.txt` - Text to append after the match

## Example

For a simple replacement rule:
- `SEARCH.txt`: "Hello world"
- `REPLACE.txt`: "Greetings planet"

## Modes

- **REPLACE**: Replaces the entire matched text
- **PREPEND**: Adds text before the matched text
- **APPEND**: Adds text after the matched text

## Requirements

- Search patterns must be at least 8 characters long
- Only one action file per rule (REPLACE.txt, PREPEND.txt, or APPEND.txt)
- Rules are applied in the order of their directory names (001, 002, etc.)

## Usage

Enable content rewriting in your configuration:

```yaml
rewriting:
  enabled: true
  config_path: "config/replacements"
```