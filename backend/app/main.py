"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.profile_check import router as profile_check_router

app = FastAPI(title="ACC → AJO Migration Tool — Backend")

# Local-first dev tool: allow any localhost origin (no cookies/credentials used).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(profile_check_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
