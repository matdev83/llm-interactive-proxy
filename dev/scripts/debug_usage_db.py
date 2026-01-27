import asyncio
import os
import sys

from sqlalchemy import func, select

# Add project root to path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from src.core.config.app_config import load_config
from src.core.database.engine import init_database
from src.core.database.models.usage import SessionMetricsTable, UsageRecordTable


async def inspect_db():
    config = load_config()
    print(f"Using database: {config.database.url}")
    engine = await init_database(config.database)

    async with engine.session() as session:
        # Check UsageRecordTable
        count_usage = (
            await session.execute(select(func.count()).select_from(UsageRecordTable))
        ).scalar()
        print(f"usage_records: {count_usage}")

        # Check SessionMetricsTable total
        stmt_max_tokens = select(func.max(SessionMetricsTable.total_tokens))
        max_tokens = (await session.execute(stmt_max_tokens)).scalar()
        print(f"Max total_tokens in session_metrics: {max_tokens}")

        stmt_with_tokens = (
            select(func.count())
            .select_from(SessionMetricsTable)
            .where(SessionMetricsTable.total_tokens > 0)
        )
        count_with_tokens = (await session.execute(stmt_with_tokens)).scalar()
        print(f"session_metrics with tokens > 0: {count_with_tokens}")

        # Check SessionMetricsTable for today
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        stmt = (
            select(func.count())
            .select_from(SessionMetricsTable)
            .where(SessionMetricsTable.last_activity >= start_of_day)
        )
        count_sessions_today = (await session.execute(stmt)).scalar()
        print(f"session_metrics (today): {count_sessions_today}")

    await engine.close()


if __name__ == "__main__":
    asyncio.run(inspect_db())
