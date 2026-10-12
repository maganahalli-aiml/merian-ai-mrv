"""Smoke tests: the API starts and its routes work WITHOUT Google Cloud (everything external is faked)."""
import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from api import endpoints
from api.main import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_status_shows_config_without_calling_gcp():
    body = client.get("/api/status").json()
    assert body["gcp"]["project_id"] == "test-project"
    assert body["models"]["embedding"] == endpoints.settings.local_embedding_model_name
    assert body["backend"]["app_mode"] == "local"
    assert body["backend"]["vector_store"] == "Chroma"


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


def test_local_upload_saves_and_indexes_without_gcs(monkeypatch, tmp_path):
    monkeypatch.setattr(endpoints.settings, "app_mode", "local")
    monkeypatch.setattr(endpoints.settings, "local_data_dir", str(tmp_path))
    monkeypatch.setattr(
        endpoints.storage,
        "Client",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("GCS must not be used in local mode")),
    )

    def fake_ingest_pdf(path, source):
        assert source == "local://policy.pdf"
        with open(path, "rb") as uploaded_file:
            assert uploaded_file.read() == b"%PDF-1.4"
        return {"pages": 1, "chunks": 1}

    monkeypatch.setattr(endpoints, "ingest_pdf", fake_ingest_pdf)
    response = client.post(
        "/api/rag/upload",
        files={"files": ("policy.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "ingested"
    assert (tmp_path / "uploads" / "policy.pdf").read_bytes() == b"%PDF-1.4"
    listed = client.get("/api/rag/uploads")
    assert listed.status_code == 200
    document = listed.json()["uploads"][0]
    assert document["filename"] == "policy.pdf"
    assert document["status"] == "ingested"
    assert document["pages"] == 1
    assert document["chunks"] == 1
    assert document["size_bytes"] == 8
    assert document["uploaded_at"]


def test_local_mode_rejects_gcs_ingestion(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(endpoints.settings, "app_mode", "local")
    with pytest.raises(HTTPException, match="APP_MODE=cloud") as error:
        endpoints.trigger_gcs_ingestion()
    assert error.value.status_code == 400


def test_local_vector_store_persists_documents(monkeypatch, tmp_path):
    from langchain_core.embeddings import Embeddings

    from backend.rag import vector_store

    class TestEmbeddings(Embeddings):
        def embed_documents(self, texts):
            return [self.embed_query(text) for text in texts]

        def embed_query(self, text):
            return [float(len(text)), 1.0, 0.0]

    monkeypatch.setattr(vector_store.settings, "app_mode", "local")
    monkeypatch.setattr(vector_store.settings, "local_data_dir", str(tmp_path))
    monkeypatch.setattr(vector_store, "get_embeddings", TestEmbeddings)
    monkeypatch.setattr(endpoints.settings, "app_mode", "local")
    monkeypatch.setattr(endpoints.settings, "local_data_dir", str(tmp_path))
    vector_store.get_vector_store.cache_clear()
    try:
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        (uploads_dir / "legacy.pdf").write_bytes(b"pdf")
        vector_store.get_vector_store().add_documents(
            [Document(
                page_content="Aldermoor procurement policy",
                metadata={"source": "local://legacy.pdf", "page": 0, "total_pages": 2},
            )]
        )

        vector_store.get_vector_store.cache_clear()
        results = vector_store.get_vector_store().similarity_search("procurement policy", k=1)
        assert results[0].page_content == "Aldermoor procurement policy"
        assert (tmp_path / "chroma").is_dir()
        listed = endpoints.list_uploads()["uploads"]
        assert listed[0]["filename"] == "legacy.pdf"
        assert listed[0]["status"] == "ingested"
        assert listed[0]["pages"] == 2
        assert listed[0]["chunks"] == 1
    finally:
        vector_store.get_vector_store.cache_clear()


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
