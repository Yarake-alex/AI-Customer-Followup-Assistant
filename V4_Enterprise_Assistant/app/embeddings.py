"""Embedding service abstraction.

Supports three providers:
  - local: sentence-transformers (BAAI/bge-m3 by default)
  - openai_compatible: any OpenAI-compatible embeddings API (Qwen, Zhipu, etc.)
  - test: deterministic hash-based embedding (no deps, for automated tests)

Lazy-loads the model on first use to avoid slowing down server startup.
"""

import hashlib
import logging
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Unified embedding interface with lazy initialization."""

    def __init__(self) -> None:
        self._model = None       # sentence-transformers model
        self._client = None      # OpenAI-compatible client
        self._dimension: int = 1024  # default, overridden after load
        self._loaded = False
        self._load_error: Optional[str] = None

    # ── public API ──

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query string."""
        self._ensure_loaded()

        if self._provider == "test":
            return self._test_embed(text, False)

        if self._model is not None:
            emb = self._model.encode(text, normalize_embeddings=True)
            return emb.tolist()

        # API path
        resp = self._client.embeddings.create(  # type: ignore[union-attr]
            model=settings.EMBEDDING_MODEL_NAME,
            input=text,
        )
        return resp.data[0].embedding

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Batch-embed multiple document strings."""
        if not texts:
            return []

        self._ensure_loaded()

        if self._provider == "test":
            return [self._test_embed(t, True) for t in texts]

        if self._model is not None:
            embs = self._model.encode(texts, normalize_embeddings=True)
            return [e.tolist() for e in embs]

        # API path — send as batch
        resp = self._client.embeddings.create(  # type: ignore[union-attr]
            model=settings.EMBEDDING_MODEL_NAME,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (available after first load)."""
        self._ensure_loaded()
        return self._dimension

    # ── init ──

    def _ensure_loaded(self) -> None:
        """Lazy-load the underlying model / client. Called on first use."""
        if self._loaded:
            if self._load_error:
                raise RuntimeError(f"Embedding service failed to load: {self._load_error}")
            return

        self._loaded = True
        self._provider = settings.EMBEDDING_PROVIDER.lower()

        try:
            if self._provider == "local":
                self._init_local()
            elif self._provider == "test":
                self._init_test()
            else:
                self._init_api()
        except Exception as exc:
            self._load_error = str(exc)
            logger.error(f"Failed to initialize embedding service (provider={self._provider}): {exc}")
            raise RuntimeError(f"Failed to initialize embedding service: {exc}") from exc

        # Validate dimension consistency
        configured_dim = settings.EMBEDDING_DIMENSION
        if configured_dim and configured_dim > 0 and self._dimension != configured_dim:
            raise RuntimeError(
                f"Embedding dimension mismatch: model returns {self._dimension}, "
                f"but EMBEDDING_DIMENSION is set to {configured_dim}. "
                f"Update EMBEDDING_DIMENSION to {self._dimension} or leave it as 0 (auto)."
            )
        if configured_dim and configured_dim > 0:
            self._dimension = configured_dim

    def _init_local(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for local embedding. "
                "Install it with: pip install -r requirements-embedding-local.txt\n"
                "Or switch to API embedding: set EMBEDDING_PROVIDER=openai_compatible"
            )

        model_name = settings.EMBEDDING_MODEL
        logger.info(f"Loading embedding model: {model_name}")
        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info(f"Embedding model loaded, dimension={self._dimension}")

    def _init_api(self) -> None:
        from openai import OpenAI

        api_key = settings.EMBEDDING_API_KEY or settings.OPENAI_API_KEY
        base_url = settings.EMBEDDING_BASE_URL or settings.OPENAI_BASE_URL

        if not api_key:
            raise ValueError(
                "EMBEDDING_API_KEY or OPENAI_API_KEY is required for API embedding provider"
            )

        self._client = OpenAI(api_key=api_key, base_url=base_url or None)

        # Detect dimension from a test call or from config
        configured_dim = settings.EMBEDDING_DIMENSION
        if configured_dim and configured_dim > 0:
            self._dimension = configured_dim
        else:
            # Make a test call to determine dimension
            test_resp = self._client.embeddings.create(  # type: ignore[union-attr]
                model=settings.EMBEDDING_MODEL_NAME,
                input="dimension probe",
            )
            self._dimension = len(test_resp.data[0].embedding)

        logger.info(
            f"Embedding API client initialized: base_url={base_url}, "
            f"model={settings.EMBEDDING_MODEL_NAME}, dimension={self._dimension}"
        )

    def _init_test(self) -> None:
        """Deterministic hash-based embedding — zero deps, for automated tests."""
        configured_dim = settings.EMBEDDING_DIMENSION
        self._dimension = configured_dim if (configured_dim and configured_dim > 0) else 128
        logger.info(f"Test embedding provider ready, dimension={self._dimension}")

    def _test_embed(self, text: str, as_list: bool) -> List[float]:
        """Hash-based deterministic embedding."""
        if as_list:
            # Use hash of text for deterministic results
            h = hashlib.sha256(text.encode("utf-8")).digest()
            # Repeat hash bytes to fill the dimension
            repeated = (h * (self._dimension // len(h) + 1))[:self._dimension]
            return [float(b) / 255.0 for b in repeated]
        else:
            return self._test_embed(text, True)


# ── module-level lazy singleton ──

_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Return the module-level EmbeddingService singleton, creating it on first call."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
