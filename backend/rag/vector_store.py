"""Select persistent local Chroma or cloud Vertex AI Vector Search."""
from functools import lru_cache
from pathlib import Path

from google.cloud import aiplatform
from langchain_chroma import Chroma
from langchain_core.vectorstores import VectorStore
from langchain_google_vertexai import VectorSearchVectorStore

try:
    from backend.exceptions import ConfigurationError
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from exceptions import ConfigurationError

try:
    from backend.config.settings import settings
    from backend.rag.embeddings import get_embeddings
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from config.settings import settings
    from rag.embeddings import get_embeddings


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Get the configured local Chroma or cloud Vertex AI vector store."""
    if settings.app_mode == "local":
        persist_directory = Path(settings.local_data_dir).expanduser() / "chroma"
        persist_directory.mkdir(parents=True, exist_ok=True)
        return Chroma(
            collection_name="meridian_documents",
            persist_directory=str(persist_directory),
            embedding_function=get_embeddings(),
        )

    missing_settings = settings.missing_cloud_settings()
    if missing_settings:
        raise ConfigurationError(
            "APP_MODE=cloud is missing required settings: "
            + ", ".join(missing_settings)
        )

    aiplatform.init(project=settings.GCP_PROJECT, location=settings.GCP_REGION)

    return VectorSearchVectorStore.from_components(
        project_id=settings.GCP_PROJECT,
        region=settings.GCP_REGION,
        embedding=get_embeddings(),  # NOTE: singular "embedding", not "embeddings"
        index_id=settings.vector_search_index_id,
        endpoint_id=settings.vector_search_index_endpoint_id,
        gcs_bucket_name=settings.GCS_BUCKET_NAME,
        stream_update=True,
    )
