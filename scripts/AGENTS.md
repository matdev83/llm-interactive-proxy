# Scripts Directory Policy

**ATTENTION AGENTS**

This directory (`/scripts`) is reserved strictly for **End User Tools**.

## What Belongs Here
- CLI tools for users to interact with the proxy (e.g., inspecting captures, listing models).
- Administration scripts intended for the deployment environment.
- Installation or setup helpers for the end user.

## What Does NOT Belong Here
- **Development Scripts**: Tools used by contributors to build, test, or lint the project. Move these to `/dev/scripts`.
- **Debugging Tools**: One-off scripts, reproduction scripts, or debug probes. Move these to `/dev/scripts` or `/dev/scripts/artifacts`.
- **Artifacts**: Temporary scripts, migration helpers, or one-time verification scripts. Move these to `/dev/scripts/artifacts`.
