"""REST endpoints. Each route is thin: validate input, call the real logic, return JSON.

    /api/health        - is the server up?
    /api/status        - configuration summary shown on the System Status tab
    /api/agent/audit   - run the multi-agent procurement audit        (agent/agents.py)
    /api/rag/ask       - ask a question about the ingested documents  (rag/retrieval.py)
    /api/rag/upload    - upload PDFs and index them                   (rag/data_ingestion.py)
    /api/rag/ingest-gcs- index every PDF already in cloud document storage
"""
import os
import platform
import json
import shutil
import sys
import tempfile
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from google.cloud import storage

try:
    from backend.agent.agents import ProcurementSupervisor
    from backend.api.schemas import AuditRequest, AuditResponse, QueryRequest, QueryResponse
    from backend.config.settings import settings
    from backend.exceptions import ConfigurationError
    from backend.logger import GLOBAL_LOGGER as log
    from backend.rag.data_ingestion import ingest_pdf, ingest_stored_pdfs
    from backend.rag.retrieval import ask_question
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from agent.agents import ProcurementSupervisor
    from api.schemas import AuditRequest, AuditResponse, QueryRequest, QueryResponse
    from config.settings import settings
    from exceptions import ConfigurationError
    from logger import GLOBAL_LOGGER as log
    from rag.data_ingestion import ingest_pdf, ingest_stored_pdfs
    from rag.retrieval import ask_question

health_router = APIRouter(prefix="/api", tags=["Health"])
status_router = APIRouter(prefix="/api", tags=["Status"])
agent_router = APIRouter(prefix="/api/agent", tags=["Agent"])
rag_router = APIRouter(prefix="/api/rag", tags=["RAG"])

# In-memory upload tracker (reset on restart)
_upload_history: list[dict] = []
_server_start_time = datetime.now(timezone.utc)


class _IndexedDocumentDetails(TypedDict):
    chunks: int
    pages: set[int]
    total_pages: int


def _save_local_upload_details(document: dict) -> None:
    metadata_path = Path(settings.local_data_dir).expanduser() / "uploads.json"
    if metadata_path.exists():
        with metadata_path.open(encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    else:
        metadata = {}
    metadata[document["filename"]] = {
        key: document[key]
        for key in ("status", "pages", "chunks", "reason", "uploaded_at")
        if key in document
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)


def _get_local_index_details() -> dict[str, dict[str, int]]:
    chroma_dir = Path(settings.local_data_dir).expanduser() / "chroma"
    if not chroma_dir.exists():
        return {}

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection_names = {collection.name for collection in client.list_collections()}
        if "meridian_documents" not in collection_names:
            return {}

        collection = client.get_collection("meridian_documents")
        metadatas = collection.get(include=["metadatas"]).get("metadatas") or []
    except Exception as error:
        log.error("Could not inspect local Chroma documents", error=str(error))
        raise HTTPException(status_code=500, detail="Could not inspect the local document index.") from error

    indexed: dict[str, _IndexedDocumentDetails] = defaultdict(
        lambda: {"chunks": 0, "pages": set(), "total_pages": 0}
    )
    for item in metadatas:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if not isinstance(source, str) or not source.startswith("local://"):
            continue
        details = indexed[source]
        details["chunks"] += 1
        page = item.get("page")
        if isinstance(page, int):
            details["pages"].add(page)
        total_pages = item.get("total_pages")
        if isinstance(total_pages, int):
            details["total_pages"] = max(details["total_pages"], total_pages)

    return {
        source: {
            "chunks": int(details["chunks"]),
            "pages": int(details["total_pages"] or len(details["pages"])),
        }
        for source, details in indexed.items()
    }


@lru_cache(maxsize=1)
def get_supervisor() -> ProcurementSupervisor:
    """Build the agents on the first audit request, not when the server starts."""
    return ProcurementSupervisor()


# ---------------------------------------------------------------------------
# Health & status
# ---------------------------------------------------------------------------

@health_router.get("/health")
def health():
    return {"status": "ok"}


@status_router.get("/status")
def system_status():
    """Return system configuration and health information (no calls to GCP)."""
    uptime_seconds = int((datetime.now(timezone.utc) - _server_start_time).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return {
        "backend": {
            "status": "healthy",
            "uptime": f"{hours:02d}h {minutes:02d}m {seconds:02d}s",
            "python_version": sys.version.split()[0],
            "platform": platform.system(),
            "app_mode": settings.app_mode,
            "vector_store": "Chroma" if settings.app_mode == "local" else "Vertex AI Vector Search",
        },
        "gcp": {
            "project_id": settings.GCP_PROJECT,
            "region": settings.GCP_REGION,
        },
        "storage": {
            "gcs_bucket": settings.GCS_BUCKET_NAME,
            "gcs_prefix": settings.GCS_PREFIX,
            "local_data_dir": settings.local_data_dir,
        },
        "vector_search": {
            "index_id": settings.vector_search_index_id or "NA",
            "endpoint_id": settings.vector_search_index_endpoint_id or "NA",
            "stream_update": True,
        },
        "models": {
            "embedding": (
                settings.local_embedding_model_name
                if settings.app_mode == "local"
                else settings.embedding_model_name
            ),
            "llm": settings.llm_model_name,
            "llm_framework": (
                "Gemini API (chat and embeddings) via LangChain"
                if settings.app_mode == "local"
                else "Gemini API (chat) + Vertex AI (embeddings) via LangChain"
            ),
        },
        "ingestion": {
            "uploads_this_session": len(_upload_history),
        },
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@agent_router.post("/audit", response_model=AuditResponse)
def run_audit(payload: AuditRequest):
    """Run the full multi-agent procurement audit and return all phase results."""
    try:
        result = get_supervisor().run_audit(payload.request_text)
        return AuditResponse(**result)
    except ConfigurationError as e:
        log.error("Audit configuration error", error=str(e))
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        log.error("Audit failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

@rag_router.post("/ask", response_model=QueryResponse)
def rag_query(payload: QueryRequest):
    """Query the RAG pipeline using the configured vector store and Gemini."""
    try:
        return QueryResponse(answer=ask_question(payload.query, payload.retriever_type))
    except ConfigurationError as e:
        log.error("RAG configuration error", error=str(e))
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        log.error("RAG query failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@rag_router.post("/upload")
async def upload_documents(files: list[UploadFile] = File(...)):
    """Accept PDFs, archive them locally or in GCS, then chunk, embed and index them."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided.")

    results = []
    tmp_dir = tempfile.mkdtemp()

    try:
        for upload in files:
            filename = os.path.basename(upload.filename or "")
            if not filename.lower().endswith(".pdf"):
                results.append({
                    "filename": filename,
                    "status": "skipped",
                    "reason": "Only PDF files are supported.",
                })
                continue

            if settings.app_mode == "local":
                uploads_dir = Path(settings.local_data_dir).expanduser() / "uploads"
                uploads_dir.mkdir(parents=True, exist_ok=True)
                local_path = str(uploads_dir / filename)
            else:
                local_path = os.path.join(tmp_dir, filename)

            with open(local_path, "wb") as f:
                f.write(await upload.read())

            if settings.app_mode == "cloud":
                try:
                    bucket = storage.Client(project=settings.GCP_PROJECT).bucket(settings.GCS_BUCKET_NAME)
                    gcs_path = f"{settings.GCS_PREFIX}{filename}"
                    bucket.blob(gcs_path).upload_from_filename(local_path, content_type="application/pdf")
                    log.info("File saved to GCS", filename=filename, gcs_path=f"gs://{settings.GCS_BUCKET_NAME}/{gcs_path}")
                except Exception as gcs_err:
                    log.warning("Could not save to GCS", error=str(gcs_err))

            # ingest_pdf is slow and blocking, so run it in a worker thread to keep the server responsive
            source = (
                f"local://{filename}"
                if settings.app_mode == "local"
                else f"upload://{filename}"
            )
            summary = await run_in_threadpool(ingest_pdf, local_path, source)

            if summary["chunks"] == 0:
                log.warning("No chunks extracted, skipping indexing", filename=filename)
                result = {
                    "filename": filename,
                    "status": "skipped",
                    "reason": "No extractable text found in PDF (may be a scanned/image-based PDF).",
                }
            else:
                log.info("Successfully ingested chunks", filename=filename, **summary)
                result = {"filename": filename, "status": "ingested", **summary}

            document_details = {
                **result,
                "pages": result.get("pages"),
                "chunks": result.get("chunks"),
                "reason": result.get("reason"),
                "size_bytes": Path(local_path).stat().st_size,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            results.append(document_details)
            if settings.app_mode == "local":
                _save_local_upload_details(document_details)
    except Exception as e:
        log.error("Upload failed", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    _upload_history.extend(results)
    return {"results": results}


@rag_router.get("/uploads")
def list_uploads():
    """Return locally persisted document details or cloud uploads from this session."""
    if settings.app_mode == "local":
        uploads_dir = Path(settings.local_data_dir).expanduser() / "uploads"
        metadata_path = Path(settings.local_data_dir).expanduser() / "uploads.json"
        if metadata_path.exists():
            try:
                with metadata_path.open(encoding="utf-8") as metadata_file:
                    metadata = json.load(metadata_file)
            except (OSError, json.JSONDecodeError) as error:
                log.error("Could not read local upload details", error=str(error))
                raise HTTPException(status_code=500, detail="Could not read local upload details.") from error
        else:
            metadata = {}

        index_details = _get_local_index_details()
        uploads = []
        if uploads_dir.exists():
            for pdf_path in sorted(uploads_dir.glob("*.pdf"), key=lambda path: path.name.lower()):
                try:
                    file_stat = pdf_path.stat()
                except OSError as error:
                    log.error("Could not inspect local upload", filename=pdf_path.name, error=str(error))
                    raise HTTPException(
                        status_code=500,
                        detail=f"Could not inspect local upload: {pdf_path.name}",
                    ) from error
                stored_details = metadata.get(pdf_path.name, {})
                indexed_details = index_details.get(f"local://{pdf_path.name}", {})
                pages = stored_details.get("pages", indexed_details.get("pages"))
                chunks = stored_details.get("chunks", indexed_details.get("chunks"))
                status = stored_details.get(
                    "status", "ingested" if indexed_details else "stored"
                )
                uploads.append({
                    "filename": pdf_path.name,
                    "status": status,
                    "pages": pages,
                    "chunks": chunks,
                    "reason": stored_details.get("reason"),
                    "size_bytes": file_stat.st_size,
                    "uploaded_at": stored_details.get(
                        "uploaded_at", datetime.fromtimestamp(file_stat.st_mtime, timezone.utc).isoformat()
                    ),
                })
        return {"uploads": uploads}

    return {"uploads": _upload_history}


@rag_router.post("/ingest-gcs")
def trigger_gcs_ingestion():
    """Index every PDF that is already in the GCS bucket."""
    if settings.app_mode != "cloud":
        raise HTTPException(
            status_code=400,
            detail="GCS ingestion is only available when APP_MODE=cloud. Upload PDF files directly in local mode.",
        )
    try:
        totals = ingest_stored_pdfs()
        return {"status": "GCS ingestion complete", **totals}
    except Exception as e:
        log.error("GCS ingestion failed", traceback=traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
