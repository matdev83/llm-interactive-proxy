# Database Configuration

The LLM Interactive Proxy uses a unified database abstraction layer based on SQLAlchemy and SQLModel. This provides portable, dialect-agnostic database access with support for multiple database backends.

## Overview

The proxy stores various operational data in a database:

- **Session Summaries** (ProxyMem): Cross-session memory and context
- **SSO Authentication**: Agent tokens, pending authorizations, rate limits
- **User Project Mappings**: Stable project IDs for memory isolation

By default, the proxy uses **SQLite** which requires no additional setup. For production deployments or multi-instance setups, **PostgreSQL** is recommended.

## Quick Start

### Default SQLite (Zero Configuration)

SQLite is the default database and works out of the box:

```bash
# Just start the proxy - SQLite database will be created automatically
python -m src.core.cli
```

The database file will be created at `./var/db/proxy.db`.

### PostgreSQL

For PostgreSQL, set the database URL:

```bash
# Via environment variable
export DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/llm_proxy"

# Or via CLI flag
python -m src.core.cli --database-url "postgresql+asyncpg://user:password@localhost:5432/llm_proxy"
```

## Configuration Methods

### Environment Variables

```bash
# Database connection URL
export DATABASE_URL="sqlite+aiosqlite:///./var/db/proxy.db"

# Connection pool settings (PostgreSQL only)
export DATABASE_POOL_SIZE=5
export DATABASE_MAX_OVERFLOW=10
export DATABASE_POOL_TIMEOUT=30

# Debug settings
export DATABASE_ECHO=false
export DATABASE_ECHO_POOL=false

# Migration settings
export DATABASE_AUTO_MIGRATE=true
```

### CLI Flags

```bash
python -m src.core.cli \
  --database-url "postgresql+asyncpg://user:pass@localhost/db" \
  --database-pool-size 10 \
  --database-max-overflow 20 \
  --database-echo
```

### YAML Configuration

Add database settings to your `config.yaml`:

```yaml
database:
  # SQLite (default)
  url: "sqlite+aiosqlite:///./var/db/proxy.db"
  
  # Connection pool (ignored for SQLite)
  pool_size: 5
  max_overflow: 10
  pool_timeout: 30
  
  # Debug logging
  echo: false
  echo_pool: false
  
  # Auto-run migrations on startup
  auto_migrate: true
```

## Database URL Format

The database URL follows SQLAlchemy's URL format:

```
dialect+driver://username:password@host:port/database
```

### SQLite Examples

```bash
# Relative path (recommended for development)
sqlite+aiosqlite:///./var/db/proxy.db

# Absolute path
sqlite+aiosqlite:////absolute/path/to/db/proxy.db

# In-memory database (for testing only)
sqlite+aiosqlite:///:memory:
```

### PostgreSQL Examples

```bash
# Basic connection
postgresql+asyncpg://user:password@localhost:5432/llm_proxy

# With SSL
postgresql+asyncpg://user:password@host:5432/db?ssl=require

# Unix socket connection
postgresql+asyncpg://user:password@/db?host=/var/run/postgresql

# Connection with options
postgresql+asyncpg://user:password@host/db?connect_timeout=10
```

## Configuration Reference

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | string | `sqlite+aiosqlite:///./var/db/proxy.db` | Database connection URL |
| `pool_size` | int | `5` | Connection pool size (1-100) |
| `max_overflow` | int | `10` | Extra connections beyond pool_size (0-100) |
| `pool_timeout` | int | `30` | Seconds to wait for a connection |
| `echo` | bool | `false` | Log SQL statements |
| `echo_pool` | bool | `false` | Log connection pool events |
| `auto_migrate` | bool | `true` | Run migrations on startup |

## SQLite vs PostgreSQL

### SQLite (Default)

**Best for:**
- Development and testing
- Single-instance deployments
- Personal proxy installations
- Low-to-moderate traffic

**Advantages:**
- Zero configuration required
- No external dependencies
- File-based, easy to backup
- Sufficient for most personal use cases

**Limitations:**
- Single writer at a time
- Not suitable for multi-instance deployments
- Limited concurrent connections

### PostgreSQL

**Best for:**
- Production deployments
- Multi-instance/load-balanced setups
- High-traffic environments
- Team/enterprise deployments

**Advantages:**
- Full ACID compliance
- Excellent concurrency support
- Advanced features (JSONB, full-text search)
- Connection pooling

**Requirements:**
- PostgreSQL 12+ server
- `asyncpg` driver (included in dependencies)

## PostgreSQL Setup

### 1. Create Database

```sql
-- Create database
CREATE DATABASE llm_proxy;

-- Create user with password
CREATE USER llm_proxy_user WITH PASSWORD 'secure_password';

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE llm_proxy TO llm_proxy_user;
```

### 2. Configure Connection

```yaml
database:
  url: "postgresql+asyncpg://llm_proxy_user:secure_password@localhost:5432/llm_proxy"
  pool_size: 10
  max_overflow: 20
```

### 3. Connection Pooling Recommendations

For production PostgreSQL deployments:

```yaml
database:
  url: "postgresql+asyncpg://user:pass@host:5432/db"
  
  # Pool size = 2 * CPU cores is a good starting point
  pool_size: 10
  
  # Allow overflow for traffic spikes
  max_overflow: 20
  
  # Reasonable timeout
  pool_timeout: 30
```

## Database Migrations

The proxy uses Alembic for database migrations. By default, migrations run automatically on startup (`auto_migrate: true`).

### Automatic Migrations

Migrations run automatically when:
- The proxy starts with `auto_migrate: true` (default)
- New tables or columns are detected

### Manual Migrations

To run migrations manually:

```bash
# Check current revision
./.venv/Scripts/python.exe -m alembic current

# Run all pending migrations
./.venv/Scripts/python.exe -m alembic upgrade head

# Rollback one migration
./.venv/Scripts/python.exe -m alembic downgrade -1

# Show migration history
./.venv/Scripts/python.exe -m alembic history
```

### Disabling Auto-Migration

For production environments where you want to control migrations:

```yaml
database:
  auto_migrate: false
```

Then run migrations as part of your deployment process:

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```

## Security Considerations

### Protecting Database Credentials

**Never commit credentials to version control:**

```yaml
# BAD - credentials in config file
database:
  url: "postgresql+asyncpg://user:actual_password@host/db"
```

**Use environment variables:**

```yaml
# GOOD - reference environment variable
database:
  url: "${DATABASE_URL}"
```

```bash
export DATABASE_URL="postgresql+asyncpg://user:password@host/db"
```

### SQLite File Permissions

For SQLite databases, ensure proper file permissions:

```bash
# Restrict access to database file
chmod 600 var/db/proxy.db

# Ensure var/db directory exists with proper permissions
mkdir -p var/db
chmod 700 var/db
```

### PostgreSQL SSL

For production PostgreSQL, always use SSL:

```yaml
database:
  url: "postgresql+asyncpg://user:pass@host:5432/db?ssl=require"
```

## Backup and Recovery

### SQLite Backup

```bash
# Simple file copy (stop proxy first for consistency)
cp var/db/proxy.db var/db/proxy.db.backup

# Or use SQLite backup command
sqlite3 var/db/proxy.db ".backup var/db/proxy.db.backup"
```

### PostgreSQL Backup

```bash
# Full database dump
pg_dump -h localhost -U llm_proxy_user llm_proxy > backup.sql

# Restore
psql -h localhost -U llm_proxy_user llm_proxy < backup.sql
```

## Troubleshooting

### Connection Issues

**SQLite "database is locked":**

This usually indicates multiple writers. Ensure only one proxy instance writes to the SQLite database at a time.

**PostgreSQL connection refused:**

- Verify PostgreSQL is running
- Check host, port, and credentials
- Ensure firewall allows connections
- Check `pg_hba.conf` for client authentication

### Migration Errors

**"Target database is not up to date":**

Run migrations manually:

```bash
./.venv/Scripts/python.exe -m alembic upgrade head
```

**"Can't locate revision":**

The migration history may be corrupted. Check `alembic_version` table:

```sql
SELECT * FROM alembic_version;
```

### Performance Issues

**Slow queries:**

Enable SQL logging to diagnose:

```yaml
database:
  echo: true
```

**Connection pool exhaustion:**

Increase pool size for high-traffic deployments:

```yaml
database:
  pool_size: 20
  max_overflow: 40
```

## Related Documentation

- [Configuration Guide](configuration.md) - Full configuration reference
- [ProxyMem Memory](proxymem-memory.md) - Cross-session memory feature
- [SSO Authentication](sso-authentication.md) - SSO and token storage
- [CLI Parameters](cli-parameters.md) - Complete CLI reference

