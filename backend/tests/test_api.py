"""Smoke tests: the API starts and its routes work WITHOUT Google Cloud (everything external is faked)."""
from fastapi.testclient import TestClient
from langchain_core.documents import Document

try:
    from backend.api import endpoints
    from backend.api.main import app
except ImportError:
    from api import endpoints
    from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_status_reports_local_mode_without_calling_gcp():
    body = client.get("/api/status").json()
    assert body["backend"]["app_mode"] == "local"
    assert body["backend"]["vector_store"] == "Chroma"
    assert body["models"]["embedding"] == "gemini-embedding-001"


def test_unknown_api_route_is_404():
    assert client.get("/api/does-not-exist").status_code == 404


def test_ask_returns_answer(monkeypatch):
    monkeypatch.setattr(endpoints, "ask_question", lambda query, retriever_type: f"answer to: {query}")
    res = client.post("/api/rag/ask", json={"query": "hello", "retriever_type": "similarity"})
    assert res.status_code == 200
    assert res.json() == {"answer": "answer to: hello"}


def test_audit_returns_all_four_sections(monkeypatch):
    class FakeSupervisor:
        def run_audit(self, text):
            return {"risk_result": "r", "tax_result": "t", "control_result": "c", "cfo_memo": "m"}

    monkeypatch.setattr(endpoints, "get_supervisor", lambda: FakeSupervisor())
    res = client.post("/api/agent/audit", json={"request_text": "buy 200 PLCs"})
    assert res.status_code == 200
    assert set(res.json()) == {"risk_result", "tax_result", "control_result", "cfo_memo"}


def test_upload_skips_non_pdf():
    res = client.post("/api/rag/upload", files={"files": ("notes.txt", b"hi", "text/plain")})
    assert res.json()["results"][0]["status"] == "skipped"


def test_cloud_upload_listing_reads_persisted_gcs_pdfs(monkeypatch):
    from datetime import datetime, timezone

    class FakeBlob:
        def __init__(self, name, size, time_created):
            self.name = name
            self.size = size
            self.time_created = time_created
            self.updated = None

    class FakeBucket:
        def list_blobs(self, prefix):
            assert prefix == "uploads/"
            return [
                FakeBlob(
                    "uploads/policy.pdf",
                    123,
                    datetime(2026, 10, 28, tzinfo=timezone.utc),
                ),
                FakeBlob("uploads/readme.txt", 20, None),
            ]

    class FakeStorageClient:
        def __init__(self, project):
            assert project == "test-project"

        def bucket(self, name):
            assert name == "test-bucket"
            return FakeBucket()

    monkeypatch.setattr(endpoints.settings, "app_mode", "cloud")
    monkeypatch.setattr(endpoints.settings, "GCP_PROJECT", "test-project")
    monkeypatch.setattr(endpoints.settings, "GCS_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(endpoints.settings, "GCS_PREFIX", "uploads/")
    monkeypatch.setattr(endpoints.storage, "Client", FakeStorageClient)
    monkeypatch.setattr(endpoints, "_upload_history", [])

    response = client.get("/api/rag/uploads")

    assert response.status_code == 200
    assert response.json()["uploads"] == [{
        "filename": "policy.pdf",
        "status": "stored",
        "pages": None,
        "chunks": None,
        "reason": None,
        "size_bytes": 123,
        "uploaded_at": "2026-10-28T00:00:00+00:00",
    }]


def test_cloud_upload_fails_if_gcs_persistence_fails(monkeypatch):
    class FakeBlob:
        def upload_from_filename(self, filename, content_type):
            raise RuntimeError("bucket access denied")

    class FakeBucket:
        def blob(self, name):
            assert name == "uploads/policy.pdf"
            return FakeBlob()

    class FakeStorageClient:
        def __init__(self, project):
            pass

        def bucket(self, name):
            return FakeBucket()

    def unexpected_ingestion(*args):
        raise AssertionError("ingestion must not run when durable storage fails")

    monkeypatch.setattr(endpoints.settings, "app_mode", "cloud")
    monkeypatch.setattr(endpoints.settings, "GCP_PROJECT", "test-project")
    monkeypatch.setattr(endpoints.settings, "GCS_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(endpoints.settings, "GCS_PREFIX", "uploads/")
    monkeypatch.setattr(endpoints.storage, "Client", FakeStorageClient)
    monkeypatch.setattr(endpoints, "ingest_pdf", unexpected_ingestion)

    response = client.post(
        "/api/rag/upload",
        files={"files": ("policy.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert "Could not save uploaded PDF to Cloud Storage" in response.json()["detail"]


def test_chunking_splits_long_text_and_keeps_metadata():
    from rag.data_ingestion import split_into_chunks

    page = Document(page_content="word " * 1000, metadata={"source": "test.pdf"})
    chunks = split_into_chunks([page])
    assert len(chunks) > 1
    assert all(c.metadata["source"] == "test.pdf" for c in chunks)
    assert all(len(c.page_content) <= 1000 for c in chunks)


def test_sample_pdfs_load_and_chunk():
    """The demo PDFs in sample_docs/ can be read and split (no Google Cloud needed)."""
    import glob
    import os

    from langchain_community.document_loaders import PyPDFLoader

    from rag.data_ingestion import split_into_chunks

    folder = os.path.join(os.path.dirname(__file__), "..", "..", "sample_docs")
    pdfs = glob.glob(os.path.join(folder, "*.pdf"))
    assert len(pdfs) == 4
    for pdf in pdfs:
        assert split_into_chunks(PyPDFLoader(pdf).load()), pdf


def test_log_lines_carry_a_severity_field_for_cloud_logging():
    from logger.custom_logger import add_severity

    assert add_severity(None, "info", {"event": "x", "level": "info"})["severity"] == "INFO"
    assert add_severity(None, "error", {"event": "x", "level": "error"})["severity"] == "ERROR"
    assert "severity" not in add_severity(None, "info", {"event": "x"})
