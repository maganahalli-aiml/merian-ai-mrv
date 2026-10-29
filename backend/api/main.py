"""
FastAPI backend — Procurement Audit & RAG Document Intelligence
================================================================
Run locally (from the project root):
    uvicorn api.main:app --app-dir backend --reload --port 8080
Interactive API docs: http://localhost:8080/docs

Exposes REST endpoints for:
  1. Running multi-agent procurement audits       (agent/agents.py)
  2. Uploading documents into the configured vector store (rag/data_ingestion.py)
  3. Querying the RAG pipeline                    (rag/retrieval.py)
In Docker / Cloud Run the same server also serves the built React app.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

try:
    from backend.api.auth import auth_router
    from backend.api.endpoints import agent_router, health_router, rag_router, status_router
    from backend.api.middleware import RequestSecurityMiddleware, RequestTooLarge
    from backend.config.settings import settings
    from backend.logger import _LOGGER_INSTANCE
    from backend.logger import GLOBAL_LOGGER as log
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from api.auth import auth_router
    from api.endpoints import agent_router, health_router, rag_router, status_router
    from api.middleware import RequestSecurityMiddleware, RequestTooLarge
    from config.settings import settings
    from logger import _LOGGER_INSTANCE
    from logger import GLOBAL_LOGGER as log


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield  # the app runs here
    # Shutdown: flush logs to GCS (critical on Cloud Run, whose disk disappears)
    _LOGGER_INSTANCE.flush_to_gcs()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent procurement audit & RAG document intelligence backend.",
    lifespan=lifespan,
    docs_url=None if settings.is_cloud else "/docs",
    redoc_url=None if settings.is_cloud else "/redoc",
    openapi_url=None if settings.is_cloud else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(RequestSecurityMiddleware)


@app.exception_handler(RequestTooLarge)
async def request_too_large_handler(request: Request, _: RequestTooLarge) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": "Upload request exceeds the configured size limit."},
    )

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(status_router)
app.include_router(agent_router)
app.include_router(rag_router)


# ============================================================
# Serve the React frontend (only exists after `npm run build`, e.g. inside Docker)
# ============================================================

frontend_dist = os.path.realpath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))

if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, "assets")), name="assets")

    # Catch-all: serve a real file if it exists, otherwise index.html (React handles the route)
    @app.get("/{catchall:path}", include_in_schema=False)
    def serve_frontend(catchall: str):
        if catchall.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = os.path.realpath(os.path.join(frontend_dist, catchall))
        if file_path.startswith(frontend_dist + os.sep) and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(frontend_dist, "index.html"))
else:
    log.warning("Frontend dist not found — frontend will not be served.", path=frontend_dist)
