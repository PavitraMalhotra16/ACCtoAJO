import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from db import UserSession, SchemaJobItem, init_db, AsyncSessionLocal, ensure_schema_columns
from config import settings
from routes.auth import router as auth_router
from routes.schemas import router as schemas_router
from routes.conversion import router as conversion_router
from routes.migrate import router as migrate_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("acc_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await ensure_schema_columns()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc))
        )
        expired = result.scalars().all()
        for s in expired:
            await db.delete(s)
        await db.commit()
        if expired:
            log.info("Cleaned up %d expired session(s)", len(expired))
    async with AsyncSessionLocal() as db:
        interrupted = await db.execute(
            select(SchemaJobItem).where(SchemaJobItem.status == "RUNNING")
        )
        stuck = interrupted.scalars().all()
        if stuck:
            log.warning("Found %d interrupted schema(s) on startup — marking as FAILED for re-run", len(stuck))
            for item in stuck:
                item.status = "FAILED"
                item.error_message = "Server restarted mid-pipeline"
            await db.commit()
    log.info("DB ready")
    yield


app = FastAPI(title="ACC→AJO Migration Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(schemas_router)
app.include_router(conversion_router)
app.include_router(migrate_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
