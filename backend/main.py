import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from db import UserSession, SchemaJobItem, init_db, AsyncSessionLocal, ensure_schema_columns
from config import settings
from routes.auth import router as auth_router
from routes.schemas import router as schemas_router
from routes.conversion import router as conversion_router
from routes.migrate import router as migrate_router
from routes.templates import router as templates_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("acc_backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    try:
        await ensure_schema_columns()
    except Exception:
        log.warning("ensure_schema_columns failed at startup — DB may have missing columns; will retry lazily at runtime")
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
app.include_router(templates_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return the real error (and log the traceback) instead of a bare 500 body,
    so the UI can show what actually went wrong. HTTPExceptions keep their own
    handler, so 4xx detail messages are unaffected."""
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


@app.get("/health")
async def health():
    return {"status": "ok"}
