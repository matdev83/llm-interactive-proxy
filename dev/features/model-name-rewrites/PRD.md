# Product Requirements Document: Model Name Rewrites

## 1. Introduction

This document outlines the requirements for the "Model Name Rewrites" feature in the LLM Interactive Proxy. This feature will provide a powerful mechanism for administrators to dynamically and conditionally rewrite the `model` parameter of incoming requests before they are processed by the proxy's routing logic.

## 2. Problem Statement

Currently, the proxy has several ways to control model selection (`--static-route`, `--default-backend`, `planning_phase`), but it lacks a flexible, rule-based system for rewriting model names supplied by the client. This makes it difficult to:

- Abstract away specific model names from client applications.
- Enforce the use of certain model backends (e.g., route all `gpt-*` requests through OpenRouter).
- Create dynamic defaults for unrecognized models.
- Seamlessly swap out backend models without requiring changes to client code.

The existing features are too rigid. For example, `--static-route` is an all-or-nothing override, and `planning_phase` only applies to the initial turns of a session.

## 3. Goals and Objectives

- **Goal**: To provide a flexible, powerful, and easy-to-configure system for rewriting client-supplied model names.
- **Objective 1**: Implement a rule-based engine that can match model names using regular expressions.
- **Objective 2**: Allow replacement strings to use capture groups from the regex match for dynamic rewriting.
- **Objective 3**: Ensure the feature is configurable via the main `config.yaml` file.
- **Objective 4**: Integrate the feature seamlessly into the existing request processing pipeline, ensuring it coexists with other features like `planning_phase` and `--static-route`.
- **Objective 5**: The feature should be robust, well-tested, and clearly documented.

## 4. Feature Requirements

### 4.1. Configuration

- The feature will be configured under a new top-level key in `config.yaml` called `model_aliases`.
- `model_aliases` will be a list of rule objects.
- Each rule object will have two string keys:
  - `pattern`: A valid Python regular expression.
  - `replacement`: The string to replace the model name with. This string can reference capture groups from the `pattern` (e.g., `\1`, `\2`).
- The rules will be processed in the order they are defined in the YAML file. The first rule that matches an incoming model name will be applied, and processing will stop.

**Example Configuration:**

```yaml
model_aliases:
  # Statically replace a specific model
  - pattern: "^claude-3-sonnet-20240229$"
    replacement: "gemini-cli-oauth-personal:gemini-1.5-flash"

  # Dynamically replace any GPT model, keeping the version
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"

  # Catch-all for any other model
  - pattern: ".*"
    replacement: "gemini-cli-oauth-personal:gemini-1.5-pro"
```

### 4.2. Logic and Integration

- The model rewrite logic will be applied in the `BackendService._resolve_backend_and_model` method.
- The rewrite will occur *after* checking for a `--static-route` override but *before* considering the `planning_phase` model. This ensures a clear and predictable order of precedence.
- If no rule in `model_aliases` matches the incoming model name, the original model name will be used.

## 5. Out of Scope

- A UI for managing aliases. Configuration will be file-based only.
- Real-time reloading of the alias configuration. A proxy restart will be required to apply changes.
