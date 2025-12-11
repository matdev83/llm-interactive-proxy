# Database Schema Documentation

## Overview

**Database Type:** SQLite (async via aiosqlite)
**Location:** `./var/db/proxy.db`
**Auto-migrate:** True

## Tables (9)

### `agent_tokens`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `id` | VARCHAR(64) | No | - | Yes |
| `token_hash` | VARCHAR(256) | No | - |  |
| `user_id` | VARCHAR(256) | No | - |  |
| `user_email` | VARCHAR(512) | No | - |  |
| `provider` | VARCHAR(64) | No | - |  |
| `is_authenticated` | BOOLEAN | No | - |  |
| `is_active` | BOOLEAN | No | - |  |
| `created_at` | DATETIME | No | - |  |
| `last_authenticated_at` | DATETIME | Yes | - |  |
| `auth_expires_at` | DATETIME | Yes | - |  |

**Indexes (5):**

- `ix_agent_tokens_is_active`
- `idx_agent_tokens_token_hash`
- `ix_agent_tokens_user_id`
- `sqlite_autoindex_agent_tokens_2` (unique)
- `sqlite_autoindex_agent_tokens_1` (unique)

**Current rows:** 0

### `pending_authorizations`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `id` | VARCHAR(64) | No | - | Yes |
| `sso_state` | VARCHAR(256) | No | - |  |
| `user_email` | VARCHAR(512) | No | - |  |
| `user_id` | VARCHAR(256) | No | - |  |
| `provider` | VARCHAR(64) | No | - |  |
| `confirmation_code_hash` | VARCHAR(256) | No | - |  |
| `attempts_remaining` | INTEGER | No | - |  |
| `created_at` | DATETIME | No | - |  |
| `expires_at` | DATETIME | No | - |  |
| `client_ip` | VARCHAR(64) | No | - |  |

**Indexes (3):**

- `idx_pending_auth_sso_state`
- `sqlite_autoindex_pending_authorizations_2` (unique)
- `sqlite_autoindex_pending_authorizations_1` (unique)

**Current rows:** 0

### `rate_limits`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `identifier` | VARCHAR(256) | No | - | Yes |
| `failed_attempts` | INTEGER | No | - |  |
| `last_attempt_at` | DATETIME | No | - |  |
| `blocked_until` | DATETIME | Yes | - |  |

**Indexes (1):**

- `sqlite_autoindex_rate_limits_1` (unique)

**Current rows:** 0

### `schema_version`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `version` | INTEGER | No | - | Yes |
| `applied_at` | DATETIME | No | - |  |

**Current rows:** 0

### `session_metrics`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `session_id` | VARCHAR(128) | No | - | Yes |
| `start_time` | DATETIME | No | - |  |
| `last_activity` | DATETIME | No | - |  |
| `turn_count` | INTEGER | No | - |  |
| `total_tokens` | INTEGER | No | - |  |
| `total_tool_calls` | INTEGER | No | - |  |
| `is_completed` | BOOLEAN | No | - |  |
| `backend_type` | VARCHAR(64) | Yes | - |  |
| `model` | VARCHAR(256) | Yes | - |  |
| `proxy_user` | VARCHAR(256) | Yes | - |  |

**Indexes (6):**

- `idx_session_metrics_last_activity`
- `ix_session_metrics_proxy_user`
- `idx_session_metrics_user_activity`
- `ix_session_metrics_is_completed`
- `ix_session_metrics_last_activity`
- `sqlite_autoindex_session_metrics_1` (unique)

**Current rows:** 0

### `session_summaries`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `id` | VARCHAR(64) | No | - | Yes |
| `user_id` | VARCHAR(256) | No | - |  |
| `tenant_id` | VARCHAR(256) | Yes | - |  |
| `project_id` | VARCHAR(256) | Yes | - |  |
| `project_root` | VARCHAR(1024) | Yes | - |  |
| `session_id` | VARCHAR(64) | No | - |  |
| `session_start` | DATETIME | No | - |  |
| `client_agent` | VARCHAR(256) | Yes | - |  |
| `backend_model` | VARCHAR(256) | No | - |  |
| `title` | VARCHAR(512) | No | - |  |
| `scope` | VARCHAR(1024) | Yes | - |  |
| `goals` | VARCHAR | Yes | - |  |
| `modified_files` | VARCHAR | Yes | - |  |
| `remaining_tasks` | VARCHAR | Yes | - |  |
| `git_operations` | VARCHAR | Yes | - |  |
| `operations_performed` | VARCHAR | Yes | - |  |
| `open_questions` | VARCHAR | Yes | - |  |
| `tests_run` | VARCHAR | Yes | - |  |
| `errors` | VARCHAR | Yes | - |  |
| `key_decisions` | VARCHAR | Yes | - |  |
| `risks_or_warnings` | VARCHAR | Yes | - |  |
| `evidence` | VARCHAR | Yes | - |  |
| `branch` | VARCHAR(256) | Yes | - |  |
| `head_sha` | VARCHAR(64) | Yes | - |  |
| `completion_status` | VARCHAR(64) | Yes | - |  |
| `full_analysis` | VARCHAR | Yes | - |  |
| `summary_version` | VARCHAR(32) | No | - |  |
| `created_at` | DATETIME | No | - |  |

**Indexes (6):**

- `ix_session_summaries_user_id`
- `idx_session_summaries_user_tenant`
- `idx_session_summaries_user_session_start`
- `idx_session_summaries_session_start`
- `idx_session_summaries_user_project`
- `sqlite_autoindex_session_summaries_1` (unique)

**Current rows:** 0

### `sso_login_tokens`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `token` | VARCHAR(256) | No | - | Yes |
| `created_at` | DATETIME | No | - |  |
| `expires_at` | DATETIME | No | - |  |
| `agent_token_id` | VARCHAR(64) | Yes | - |  |

**Indexes (3):**

- `ix_sso_login_tokens_agent_token_id`
- `idx_login_token_agent_token`
- `sqlite_autoindex_sso_login_tokens_1` (unique)

**Current rows:** 0

### `usage_records`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `id` | VARCHAR(64) | No | - | Yes |
| `timestamp` | DATETIME | No | - |  |
| `session_id` | VARCHAR(128) | No | - |  |
| `turn_number` | INTEGER | No | - |  |
| `backend_type` | VARCHAR(64) | No | - |  |
| `model` | VARCHAR(256) | No | - |  |
| `frontend_type` | VARCHAR(64) | No | - |  |
| `leg` | VARCHAR(8) | No | - |  |
| `verbatim_prompt_tokens` | INTEGER | No | - |  |
| `verbatim_completion_tokens` | INTEGER | No | - |  |
| `mutated_prompt_tokens` | INTEGER | No | - |  |
| `mutated_completion_tokens` | INTEGER | No | - |  |
| `total_tokens` | INTEGER | No | - |  |
| `backend_reported_usage_json` | TEXT | Yes | - |  |
| `http_status_code` | INTEGER | Yes | - |  |
| `tool_call_count` | INTEGER | No | - |  |
| `tool_names_json` | TEXT | Yes | - |  |
| `ttft_ms` | FLOAT | Yes | - |  |
| `proxy_processing_ms` | FLOAT | No | - |  |
| `total_duration_ms` | FLOAT | No | - |  |
| `user_agent` | VARCHAR(512) | Yes | - |  |
| `app_title` | VARCHAR(256) | Yes | - |  |
| `proxy_user` | VARCHAR(256) | Yes | - |  |

**Indexes (13):**

- `idx_usage_records_proxy_user_timestamp`
- `ix_usage_records_total_tokens`
- `idx_usage_records_backend_model`
- `idx_usage_records_timestamp`
- `ix_usage_records_backend_type`
- `idx_usage_records_status_timestamp`
- `ix_usage_records_proxy_user`
- `ix_usage_records_session_id`
- `ix_usage_records_http_status_code`
- `ix_usage_records_model`
- `idx_usage_records_session_timestamp`
- `idx_usage_records_backend_model_timestamp`
- `sqlite_autoindex_usage_records_1` (unique)

**Current rows:** 0

### `user_project_dirs`

| Column | Type | Nullable | Default | Primary Key |
|--------|------|----------|---------|-------------|
| `id` | INTEGER | No | - | Yes |
| `user_id` | VARCHAR(256) | No | - |  |
| `project_root` | VARCHAR(1024) | No | - |  |

**Indexes (1):**

- `idx_user_project_dirs_unique` (unique)

**Current rows:** 0

