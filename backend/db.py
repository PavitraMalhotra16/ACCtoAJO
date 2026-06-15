"""
Simple PostgreSQL setup using SQLAlchemy + asyncpg.
Two tables: source_connections, destination_connections.
"""

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, Text, DateTime
import uuid

import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:pavitra@localhost:5432/acc_ajo")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class SourceConnection(Base):
    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    encrypted_password: Mapped[str] = mapped_column(Text, nullable=False)
    session_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DestinationConnection(Base):
    __tablename__ = "destination_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sandbox_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
