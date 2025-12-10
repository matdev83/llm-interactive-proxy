# Database-Backed Usage Tracking

## Overview

The Universal LLM Proxy uses a **database-backed usage tracking system** to record and aggregate all LLM API usage across sessions, models, and backends. This provides detailed visibility into token consumption, costs, and performance metrics.

## Architecture

### Components

1. **DatabaseEngine** (`src/core/database/engine.py`)
   - Manages SQLAlchemy async engine and session factory
   - Auto-creates tables on startup (when `auto_migrate: true`)
   - Provides connection pooling and transaction management

2. **SqlUsageStore** (`src/core/services/sql_usage_store.py`)
   - Storage layer for usage records
   - Implements async/sync bridge for compatibility
   - Persists records immediately to database

3. **UsageRecordingService** (`src/core/services/usage_recording_service.py`)
   - High-level service for recording usage
   - Creates and updates `UsageRecord` domain objects
   - Used by middleware to track request/response cycles

4. **StatisticsAggregationService** (`src/core/services/statistics_aggregation_service.py`)
   - Aggregates usage data with filters
   - Provides statistics by model, backend, frontend, leg, etc.
   - Powers the `/api/v1/usage` endpoint

### Data Flow

```
┌─────────────────┐
│  Request        │
│  Middleware     │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ UsageRecordingService   │
│ .record_request()       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ SqlUsageStore           │
│ .add_record()           │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│ Database                │
│ usage_records table     │
└─────────────────────────┘
```

## Database Schema

### `usage_records` Table

The primary table for tracking all LLM usage:

| Column | Type | Description |
|--------|------|-------------|
| `id` | VARCHAR(64) | Primary key (UUID) |
| `session_id` | VARCHAR(128) | Session identifier |
| `backend_type` | VARCHAR(64) | Backend type (e.g., "openai", "gemini") |
| `model` | VARCHAR(256) | Model name (e.g., "gpt-4", "gemini-pro") |
| `frontend_type` | VARCHAR(64) | Frontend API type (e.g., "openai", "anthropic") |
| `leg` | VARCHAR(3) | Request leg: "PTC" (Proxy-to-Client), "PTB" (Proxy-to-Backend), etc. |
| `original_prompt_tokens` | INTEGER | Original prompt tokens from backend |
| `mutated_prompt_tokens` | INTEGER | Mutated prompt tokens (after middleware) |
| `original_completion_tokens` | INTEGER | Original completion tokens from backend |
| `mutated_completion_tokens` | INTEGER | Mutated completion tokens (after middleware) |
| `total_tokens` | INTEGER | Total tokens (prompt + completion) |
| `http_status_code` | INTEGER | HTTP status code of response |
| `timestamp` | DATETIME | When the record was created |
| `proxy_user` | VARCHAR(256) | User identifier (from auth) |
| `estimated_cost_usd` | FLOAT | Estimated cost in USD |

**Indexes:**
- `idx_usage_records_session_id` - Fast lookup by session
- `idx_usage_records_backend_type` - Fast aggregation by backend
- `idx_usage_records_model` - Fast aggregation by model
- `idx_usage_records_timestamp` - Fast time-range queries

## Configuration

### `config.yaml`

```yaml
# Database configuration
database:
  url: "sqlite+aiosqlite:///./var/db/proxy.db"
  auto_migrate: true
  echo: false  # Set to true for verbose SQL logging
  echo_pool: false

# Usage tracking configuration
usage_tracking:
  enabled: true
  # Note: persistence_path, flush_interval_seconds, and max_records_in_memory
  # are ignored when using database backend (always persists immediately)
```

### Environment Variables

- `DATABASE_URL` - Override database URL
- `DATABASE_ECHO` - Enable SQL query logging (true/false)

## Usage

### Initialization

The database is automatically initialized during application startup:

1. **Infrastructure Stage** (`src/core/app/stages/infrastructure.py`)
   - Creates `DatabaseEngine` instance
   - Calls `db_engine.initialize()` to create tables
   - Registers engine in DI container

2. **Core Services Stage** (`src/core/app/stages/core_services.py`)
   - Creates `SqlUsageStore` with database session factory
   - Registers `UsageRecordingService` and `StatisticsAggregationService`

### Recording Usage

Usage is automatically recorded by middleware. Manual recording:

```python
from src.core.services.usage_recording_service import UsageRecordingService
from src.core.domain.usage_record import UsageRecord, Leg

# Get service from DI container
recording_service = service_provider.get_required_service(UsageRecordingService)

# Create and record usage
record = UsageRecord(
    id="unique-id",
    session_id="session-123",
    backend_type="openai",
    model="gpt-4",
    frontend_type="openai",
    leg=Leg.PTC,
    mutated_prompt_tokens=100,
    mutated_completion_tokens=50,
    total_tokens=150,
    http_status_code=200,
)

recording_service.record_request(record)
```

### Querying Statistics

```python
from src.core.services.statistics_aggregation_service import StatisticsAggregationService
from src.core.domain.statistics_filter import StatisticsFilter

# Get service from DI container
stats_service = service_provider.get_required_service(StatisticsAggregationService)

# Query with filters
filter = StatisticsFilter(
    backend_type="openai",
    model="gpt-4",
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 12, 31),
)

stats = stats_service.get_aggregated_stats(filter)

# Returns:
# {
#   "gpt-4": {
#     "total_tokens": 150000,
#     "prompt_tokens": 100000,
#     "completion_tokens": 50000,
#     "cost": 3.0,
#     "requests": 100
#   }
# }
```

### API Endpoint

GET `/api/v1/usage` - Query usage statistics

**Query Parameters:**
- `backend_type` - Filter by backend (e.g., "openai")
- `model` - Filter by model (e.g., "gpt-4")
- `frontend_type` - Filter by frontend API
- `leg` - Filter by leg ("PTC", "PTB", etc.)
- `start_date` - Start date (ISO 8601)
- `end_date` - End date (ISO 8601)
- `proxy_user` - Filter by user

**Example:**
```bash
curl "http://localhost:8000/api/v1/usage?backend_type=openai&model=gpt-4"
```

## Database Maintenance

### Backup

SQLite database can be backed up with simple file copy:

```bash
# Stop the proxy first (to ensure no writes in progress)
cp var/db/proxy.db var/db/proxy.db.backup

# Or use SQLite's online backup
sqlite3 var/db/proxy.db ".backup var/db/proxy.db.backup"
```

### Cleanup Old Records

Currently no automatic cleanup. To manually delete old records:

```sql
DELETE FROM usage_records WHERE timestamp < datetime('now', '-30 days');
```

Consider adding a retention policy in future versions.

### Migration to PostgreSQL

For production environments with multiple proxy instances:

1. Update `config.yaml`:
```yaml
database:
  url: "postgresql+asyncpg://user:pass@localhost/proxy_db"
  auto_migrate: true
```

2. Create PostgreSQL database:
```sql
CREATE DATABASE proxy_db;
```

3. Restart proxy - tables will be auto-created

4. Optionally migrate existing SQLite data using ETL tools

## Monitoring

### Startup Logs

On successful initialization, you'll see:

```
INFO:src.core.database.engine:Creating async database engine for: sqlite+aiosqlite:///./var/db/proxy.db
INFO:src.core.database.engine:Database schema initialized
INFO:src.core.app.stages.infrastructure:Database initialized successfully
INFO:src.core.app.stages.core_services:Usage tracking services registered successfully with database persistence
```

### SQL Query Logging

Enable detailed SQL logging in `config.yaml`:

```yaml
database:
  echo: true  # Logs all SQL queries
  echo_pool: true  # Logs connection pool activity
```

### Database Statistics

Check database size and row counts:

```bash
# Database file size
ls -lh var/db/proxy.db

# Row counts
sqlite3 var/db/proxy.db "SELECT COUNT(*) FROM usage_records"
```

## Troubleshooting

### Database Not Created

**Symptom:** No `var/db/proxy.db` file after startup

**Solutions:**
1. Check `database.auto_migrate` is `true` in config
2. Verify `var/db/` directory exists (create if needed)
3. Check startup logs for initialization errors
4. Verify SQLAlchemy and aiosqlite are installed

### No Usage Records

**Symptom:** Database exists but no records written

**Solutions:**
1. Check `usage_tracking.enabled` is `true` in config
2. Verify requests are actually being made to the proxy
3. Enable SQL logging to see INSERT statements
4. Check logs for errors in `UsageRecordingService`

### Performance Issues

**Symptom:** Slow queries or high latency

**Solutions:**
1. Ensure indexes exist (check with `PRAGMA index_list(usage_records)`)
2. Add compound indexes for common filter combinations
3. Consider connection pooling settings
4. Migrate to PostgreSQL for better concurrent write performance
5. Implement batch writes instead of per-request commits

## Performance Characteristics

### SQLite (Default)

- **Writes:** ~50,000 inserts/sec (synchronous), ~1,000/sec (fsync enabled)
- **Reads:** Very fast with indexes
- **Concurrency:** Single writer, multiple readers
- **Best for:** Single proxy instance, moderate traffic

### PostgreSQL (Recommended for Production)

- **Writes:** ~10,000-50,000 inserts/sec (depends on configuration)
- **Reads:** Very fast with proper indexes
- **Concurrency:** Multiple writers and readers
- **Best for:** Multiple proxy instances, high traffic

## Future Enhancements

- [ ] Automatic retention policy (delete records older than N days)
- [ ] Cost calculation based on model pricing
- [ ] Batch write support for high throughput
- [ ] Database connection pool configuration
- [ ] Alembic migration support (instead of auto-create)
- [ ] Partitioning for large datasets
- [ ] Real-time metrics dashboard
- [ ] Export to analytics platforms (BigQuery, Snowflake)
