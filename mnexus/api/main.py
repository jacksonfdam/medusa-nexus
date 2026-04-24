"""FastAPI surface for the web UI.

Local-first: by default bound to 127.0.0.1. Don't expose this to the internet.
You are holding APKs, keys, and traffic captures. Act accordingly.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.nexus = MedusaNexus(NexusConfig.from_env())
    yield
    app.state.nexus.db.close()


app = FastAPI(
    title="MEDUSA NEXUS",
    description="Unified Mobile Threat Analysis Platform — local REST surface.",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "tagline": "every head sees a different angle"}


@app.get("/v1/doctor")
async def doctor() -> list[dict[str, Any]]:
    nexus: MedusaNexus = app.state.nexus
    return await nexus.doctor()


@app.get("/v1/projects")
async def list_projects() -> list[dict[str, Any]]:
    nexus: MedusaNexus = app.state.nexus
    return nexus.db.list_projects()


@app.get("/v1/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    nexus: MedusaNexus = app.state.nexus
    project = nexus.db.load_project(project_id)
    if not project:
        return {"error": "not_found", "id": project_id}
    return project.model_dump(mode="json")
