from __future__ import annotations

from typing import Any


class SentenceTransformerEmbedder:
    """Adaptateur local SentenceTransformers, remplaçable sans toucher au retrieval."""

    def __init__(self, model_name: str, device: str | None = None, model: Any | None = None):
        self.model_name = model_name
        if model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "sentence-transformers est requis pour charger le modèle local."
                ) from exc
            model = (
                SentenceTransformer(model_name, device=device)
                if device
                else SentenceTransformer(model_name)
            )
        self.model = model
        self.dimension = int(self.model.get_embedding_dimension())

    def encode(self, text: str, normalize: bool = True):
        """Encode une requête avec la même forme que l'implémentation historique."""
        vector = self.model.encode(
            [text],
            convert_to_numpy=True,
            normalize_embeddings=normalize,
        )[0]
        try:
            import numpy as np
            return vector.astype(np.float32)
        except ImportError:  # pragma: no cover
            return vector
