from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from handoff.config import Settings

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.sqlalchemy_url, pool_size=10, max_overflow=5, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(settings: Settings) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.attributes["url"] = settings.sqlalchemy_url
    return config


async def migrate(settings: Settings) -> None:
    """Bring the application schema to the latest Alembic revision."""
    await asyncio.to_thread(command.upgrade, alembic_config(settings), "head")
