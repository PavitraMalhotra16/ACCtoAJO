"""
PostgreSQL setup — only tables used by the active migration tool.
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:pavitra@localhost:5432/acc_ajo")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class SourceConnection(Base):
    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    auth_type: Mapped[str] = mapped_column(String(50), default="classic")
    instance_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # classic auth
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    security_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    # classic auth — SOAP session expiry (ACC default ~24h, no expiry returned by Logon)
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # technical auth (mirrors DestinationConnection pattern)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DestinationConnection(Base):
    __tablename__ = "destination_connections"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    org_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sandbox_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authenticated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ConvertedSchema(Base):
    __tablename__ = "converted_schemas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)
    enriched_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class SchemaJobItem(Base):
    __tablename__ = "schema_job_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    schema_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="QUEUED")
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_step_order: Mapped[int] = mapped_column(Integer, default=0)
    identity_is_primary: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    current_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields_added: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    aep_dataset_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oc_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    oc_not_supported_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    oc_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oc_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantConfig(Base):
    __tablename__ = "tenant_config"

    org_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sandbox_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sandbox_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # JSON array of {code, name, id, idType} from AEP Identity Namespace API
    namespaces_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TemplateFolderConfig(Base):
    __tablename__ = "template_folder_config"
    __table_args__ = (UniqueConstraint("destination_conn_id", "channel", name="uq_folder_dest_channel"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    destination_conn_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)          # 'email' | 'sms'
    folder_name: Mapped[str] = mapped_column(String(255), nullable=False)     # user-typed sample name
    parent_folder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TemplateMigrationRun(Base):
    __tablename__ = "template_migration_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    destination_conn_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    placeholder_map: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: {"recipient.email": "profile.workEmail.address", ...}
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TemplateJobItem(Base):
    __tablename__ = "template_job_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # = TemplateMigrationRun.run_id
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    internal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING")
    current_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_step_order: Mapped[int] = mapped_column(Integer, default=0)
    enriched_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ajo_template_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AccTemplateRaw(Base):
    """Stores the raw delivery XML exactly as returned from ACC SOAP API."""
    __tablename__ = "acc_deliverytemplate_raw"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    raw_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AccTemplateParsed(Base):
    """Stores the parsed JSON extracted from the raw delivery XML."""
    __tablename__ = "acc_deliverytemplate_parsed"
    __table_args__ = (
        UniqueConstraint("login_id", "source_id", name="uq_template_parsed_login_source"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    template_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AccWorkflowRaw(Base):
    """Stores the raw workflow XML exactly as returned from ACC SOAP API."""
    __tablename__ = "acc_workflow_raw"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    internal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AccWorkflowParsed(Base):
    """Stores the parsed JSON extracted from the raw workflow XML."""
    __tablename__ = "acc_workflow_parsed"
    __table_args__ = (
        UniqueConstraint("login_id", "internal_name", name="uq_workflow_parsed_login_internal"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    login_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    internal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    workflow_data: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    # AJO migration result
    ajo_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ajo_version_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ajo_workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    migration_status: Mapped[str | None] = mapped_column(String(50), nullable=True)  # SUCCESS | FAILED | SKIPPED
    migration_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


log = logging.getLogger("acc_backend.db")

_MANAGED_TABLES = {"source_connections", "destination_connections"}


async def ensure_schema_columns() -> None:
    """
    Compare ORM model columns against the live DB for managed tables.
    Issues ALTER TABLE ... ADD COLUMN IF NOT EXISTS for any missing non-PK columns.
    Safe to call multiple times (IF NOT EXISTS is idempotent).
    """
    try:
        async with engine.connect() as conn:
            for mapper in Base.registry.mappers:
                table = mapper.class_.__table__
                if table.name not in _MANAGED_TABLES:
                    continue

                result = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = :tname AND table_schema = 'public'"
                    ),
                    {"tname": table.name},
                )
                existing = {row[0] for row in result.fetchall()}

                for col in table.columns:
                    if col.primary_key or col.name in existing:
                        continue
                    col_type = col.type.compile(dialect=conn.dialect)
                    nullability = "" if col.nullable is not False else " NOT NULL"
                    await conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" '
                            f'ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}{nullability}'
                        )
                    )
                    log.warning(
                        "Added missing column %r to table %r", col.name, table.name
                    )

            await conn.commit()
    except Exception:
        log.exception("ensure_schema_columns failed — DB may be unavailable or misconfigured")
        raise


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
        # Add columns introduced after initial table creation (create_all won't ALTER existing tables)
        for stmt in [
            "ALTER TABLE destination_connections ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(255)",
            "ALTER TABLE converted_schemas ADD COLUMN IF NOT EXISTS enriched_json TEXT",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS fields_added INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE acc_deliverytemplate_raw ADD COLUMN IF NOT EXISTS batch_id VARCHAR(255)",
            "ALTER TABLE acc_deliverytemplate_parsed ADD COLUMN IF NOT EXISTS batch_id VARCHAR(255)",
            "ALTER TABLE acc_deliverytemplate_parsed DROP CONSTRAINT IF EXISTS uq_template_parsed_login_source",
            "ALTER TABLE acc_deliverytemplate_parsed ADD CONSTRAINT uq_template_parsed_login_source UNIQUE (login_id, source_id)",
            "ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS session_expires_at TIMESTAMPTZ",
            "ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS client_id VARCHAR(255)",
            "ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS encrypted_credentials TEXT",
            "ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS encrypted_access_token TEXT",
            "ALTER TABLE source_connections ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS aep_dataset_id VARCHAR(255)",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS oc_supported BOOLEAN",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS oc_not_supported_reason TEXT",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS oc_job_id VARCHAR(255)",
            "ALTER TABLE schema_job_items ADD COLUMN IF NOT EXISTS oc_status VARCHAR(50)",
            "ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS namespaces_json TEXT",
            "ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS sandbox_id VARCHAR(255)",
            "ALTER TABLE tenant_config ADD COLUMN IF NOT EXISTS sandbox_type VARCHAR(100)",
        ]:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception:
                pass
