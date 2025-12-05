# Configurable Routing Policies

## Goal
Empower administrators to restrict which routing methods are available to users, enhancing security and control over backend usage.

## Problem
Currently, the system allows users to route requests using three methods:
1.  **Explicit Instance ID**: `<backend>.<id>:<model>` (e.g., `openai.1:gpt-4`)
2.  **Backend Name**: `<backend>:<model>` (e.g., `openai:gpt-4`, which load balances across available instances)
3.  **Model Name Only**: `<model>` (e.g., `gpt-4`, which discovers supporting backends)

In some environments, administrators may want to enforce specific routing patterns. For example, they might want to hide internal instance IDs (`openai.1`) or force users to always specify a backend provider (disabling model-only routing).

## Solution
Introduce configuration options (CLI flags, environment variables, and config file entries) to selectively disable each of these routing methods.

## Scope
-   Add configuration options to `AppConfig`.
-   Update `BackendRoutingService` to enforce these restrictions.
-   Add CLI flags and environment variable support.
-   Update documentation.
