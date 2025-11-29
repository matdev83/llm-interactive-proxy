# Improvement Proposal: Add `--version` Flag to CLI

## Overview

The `llm-interactive-proxy` project is a robust and feature-rich application. However, it currently lacks a standard `--version` flag in its CLI interface. Adding this feature is a low-effort, high-value improvement that aligns with standard CLI best practices and improves the user experience for deployment and debugging.

## Rationale

1.  **Standard Practice:** Most CLI tools provide a `--version` flag to quickly check the installed version.
2.  **Debugging:** When users report issues, knowing the exact version they are running is critical.
3.  **Deployment:** Automation scripts often check versions to ensure compatibility or to decide whether to upgrade.
4.  **Low Effort:** The version information is already available in `pyproject.toml` or `src/core/metadata.py` (implied). Implementing this requires minimal code changes.

## Implementation Plan

1.  **Modify `src/core/cli.py`**:
    *   Import `importlib.metadata` (or use existing metadata utilities if available) to retrieve the package version.
    *   Add a `--version` argument to the `argparse` parser in `build_cli_parser`.
    *   Implement the logic to print the version and exit.

2.  **Retrieve Version**:
    *   Use `importlib.metadata.version("llm-interactive-proxy")` to dynamically fetch the installed version.
    *   Fallback to a hardcoded version or a "development" string if the package is not installed.

## Expected Behavior

```bash
$ python -m src.core.cli --version
llm-interactive-proxy 0.1.0
```

## Effort vs. Gain

*   **Effort:** Very Low (approx. 10-15 lines of code).
*   **Gain:** Medium (Improved UX, easier debugging, standard compliance).
*   **Ratio:** Excellent.

This simple addition significantly polishes the CLI experience without introducing complex dependencies or risks.
