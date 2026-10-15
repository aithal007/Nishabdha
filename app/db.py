"""Async SQLAlchemy engine/session. SQLite runs in WAL mode so the dashboard can read while calls write."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_async_engine(
    _settings.db_url,
    future=True,
    connect_args={"timeout": 30} if _settings.db_url.startswith("sqlite") else {},
)

if _settings.db_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as s:
        yield s


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For background tasks / websockets: commits on success, rolls back on error."""
    async with SessionLocal() as s:
        try:
            yield s
            await s.commit()
        except Exception:
            await s.rollback()
            raise


async def init_db() -> None:
    from app import models  # noqa: F401  (register tables)
    from app.core import agent_models, decisions, security_models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Additive migration v2: preserve history, invalidate approvals from the old policy.
    from sqlalchemy import update

    from app.core.security_models import SecurityMigration

    async with session_scope() as db:
        if await db.get(SecurityMigration, 2) is None:
            await db.execute(
                update(models.StepUp)
                .where(models.StepUp.status == "pending")
                .values(status="expired")
            )
            await db.execute(
                update(models.ActionRequest)
                .where(
                    models.ActionRequest.status.in_(
                        ["pending", "awaiting_stepup", "awaiting_challenge"]
                    )
                )
                .values(status="cancelled")
            )
            db.add(SecurityMigration(version=2))
        if await db.get(SecurityMigration, 3) is None:
            db.add(SecurityMigration(version=3))
