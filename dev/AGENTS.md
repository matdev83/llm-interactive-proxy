# Development Directory Policy

**ATTENTION AGENTS**

This directory (`/dev`) is the designated home for all **internal development tools** and artifacts.

## What Belongs Here
- **Development Tools**: Scripts used by contributors for building, testing, linting, or managing the codebase (e.g., `analyze_complexity.py`, `manage_alembic_config.py`).
- **Debugging & Research**: One-off reproduction scripts, debug probes, and experimental code.
- **Artifacts**: Legacy scripts, migration helpers, or temporary verification tools that are no longer actively used but kept for reference (put these in `/dev/scripts/artifacts`).

## What Does NOT Belong Here
- **End User Tools**: Scripts intended for the final user of the proxy (e.g., capture inspection, model listing). These MUST go in `/scripts`.
- **Production Admin**: Scripts for managing a production deployment. These MUST go in `/scripts`.

## Structure
- `/dev/scripts/`: Active scripts used for development workflow.
- `/dev/scripts/artifacts/`: Retired, one-off, or purely artifactual scripts.
