"""Pure-Python embedder via fastembed (ONNX runtime).

Default model: nomic-embed-text-v1.5 (768d, ~80 MB ONNX, no Hugging Face
token needed). Loaded lazily on first call so import time stays cheap.
"""

from __future__ import annotations

from typing import Any


class FastEmbedEmbedder:
    kind = "fastembed"

    def __init__(self, model: str, query_prefix: str = "", document_prefix: str = ""):
        self.model = model
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self._model: Any | None = None
        self._dim: int | None = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._ensure_loaded()
        assert self._dim is not None
        return self._dim

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from fastembed import TextEmbedding  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "fastembed is not installed. Install with `pip install fastembed`, "
                "or pick a different embedder.kind in your config "
                "(openai-compatible, hydra-llm)."
            ) from e
        self._model = TextEmbedding(model_name=self.model)
        # Probe dimension with a tiny embedding.
        sample = list(self._model.embed(["probe"]))[0]
        self._dim = int(len(sample))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        prefixed = [f"{self.document_prefix}{t}" for t in texts] if self.document_prefix else texts
        assert self._model is not None
        return [list(map(float, v)) for v in self._model.embed(prefixed)]

    def embed_query(self, text: str) -> list[float]:
        self._ensure_loaded()
        prefixed = f"{self.query_prefix}{text}" if self.query_prefix else text
        assert self._model is not None
        return list(map(float, list(self._model.embed([prefixed]))[0]))
