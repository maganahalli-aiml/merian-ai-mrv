"""Text -> vector conversion, used both when indexing documents and when searching.

In cloud mode, embeddings must match the configured Vertex AI Vector Search index
(currently 768 dimensions). Local Chroma stores its own embedding dimensions.
"""
from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_google_vertexai import VertexAIEmbeddings

try:
    from backend.config.settings import settings
except ImportError:  # pragma: no cover - supports running with `--app-dir backend`
    from config.settings import settings


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings | VertexAIEmbeddings:
    if settings.app_mode == "local":
        if not settings.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY is required for local document embedding. "
                "Add a Gemini API key to .env."
            )
        return GoogleGenerativeAIEmbeddings(
            model=settings.local_embedding_model_name,
            google_api_key=settings.GOOGLE_API_KEY,
        )

    return VertexAIEmbeddings(model_name=settings.embedding_model_name)
