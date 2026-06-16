from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from handoff.db.models import Base

# API and worker both migrate on startup; the lock makes the second one wait and then find
# nothing left to do instead of racing on alembic_version.
_MIGRATION_LOCK = 7_104_001

url: str = context.config.attributes["url"]
engine = create_engine(url, poolclass=NullPool)

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK})
        context.run_migrations()
engine.dispose()
